"""FastAPI 진입점.

V-World 인증키는 프론트엔드로 내보내지 않는다. 배경지도 타일과 필지 조회를
모두 이 서버가 중계하므로 키는 서버 밖으로 나가지 않는다.
"""
import asyncio
import contextlib
import hashlib
import os
from collections import OrderedDict
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, crs, jobs, licensing, mailer, notices, usage
from .geom import BBox
from .sources import vworld

WEB = Path(__file__).resolve().parent.parent / "web"

VALID_LAYERS = {"parcel", "pnu"}
TILE_LAYERS = {"Base": "png", "gray": "png", "midnight": "png",
               "Satellite": "jpeg", "Hybrid": "png"}


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_sweeper())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _sweeper():
    while True:
        await asyncio.sleep(1800)
        try:
            jobs.sweep_expired()
        except OSError:
            pass


app = FastAPI(title="지적도 DXF 추출 서비스", lifespan=lifespan)


@app.get("/api/config")
async def get_config():
    return {
        "max_area_km2": config.MAX_AREA_KM2,
        "has_vworld_key": bool(config.VWORLD_KEY),
        "crs": crs.catalog(),
        "default_crs": crs.DEFAULT,
        "stages": [{"key": k, "label": v} for k, v in jobs.STAGES],
        # 직결 모드일 때만 배경지도용 인증키를 내려준다. 지적 조회는 이 값과
        # 무관하게 언제나 서버가 대신 호출한다.
        "tile_direct": config.TILE_DIRECT,
        "tile_url": (config.VWORLD_TILE_URL.replace("{key}", config.VWORLD_KEY)
                     if config.TILE_DIRECT and config.VWORLD_KEY else None),
        "tile_layers": TILE_LAYERS,
        "bank": config.BANK_INFO,
        "demo_days": config.DEMO_DAYS,
        "has_package": (WEB / "download" / "CADMAP-setup.zip").exists(),
        "youtube": config.YOUTUBE_ID,
    }


# 타일은 한 번 받으면 바뀌지 않는다. 같은 타일을 V-World에 다시 묻지 않도록
# 메모리에 들고 있는다. 8000장이면 대략 80 MB 안쪽이다.
_TILE_CACHE: "OrderedDict[str, tuple[bytes, str]]" = OrderedDict()
_TILE_CACHE_MAX = int(os.getenv("TILE_CACHE_MAX", "8000"))
_tile_lock = asyncio.Lock()
# 같은 타일을 동시에 여러 번 요청해도 V-World에는 한 번만 간다.
_tile_inflight: dict[str, asyncio.Future] = {}


@app.get("/api/tiles/{layer}/{z}/{y}/{x}")
async def tile(layer: str, z: int, y: int, x: int):
    """V-World WMTS 중계.

    인증키를 브라우저에 노출하지 않으려고 서버가 대신 받아 준다. 대신 왕복이
    길어지므로 메모리에 캐시하고, 응답 헤더로 Cloudflare 엣지에도 캐시시킨다.
    """
    if layer not in TILE_LAYERS:
        raise HTTPException(404, "알 수 없는 배경지도")
    if not config.VWORLD_KEY:
        raise HTTPException(503, "V-World 인증키가 설정되지 않았습니다.")

    ext = TILE_LAYERS[layer]
    key = f"{layer}/{z}/{y}/{x}"

    hit = _TILE_CACHE.get(key)
    if hit is not None:
        _TILE_CACHE.move_to_end(key)
        return _tile_response(hit[0], hit[1], cached=True)

    async with _tile_lock:
        fut = _tile_inflight.get(key)
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            _tile_inflight[key] = fut
            owner = True
        else:
            owner = False

    if not owner:
        data, ctype = await fut
        if data is None:
            return Response(status_code=204)
        return _tile_response(data, ctype, cached=True)

    url = config.VWORLD_TILE_URL.format(
        key=config.VWORLD_KEY, layer=layer, z=z, y=y, x=x, ext=ext)
    ctype = "image/jpeg" if ext == "jpeg" else "image/png"
    data = None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers={"User-Agent": config.USER_AGENT})
        if r.status_code == 200:
            data = r.content
            _TILE_CACHE[key] = (data, ctype)
            while len(_TILE_CACHE) > _TILE_CACHE_MAX:
                _TILE_CACHE.popitem(last=False)
    except httpx.HTTPError:
        data = None
    finally:
        async with _tile_lock:
            _tile_inflight.pop(key, None)
        if not fut.done():
            fut.set_result((data, ctype))

    if data is None:
        return Response(status_code=204)
    return _tile_response(data, ctype)


def _tile_response(data: bytes, ctype: str, cached: bool = False) -> Response:
    return Response(
        content=data,
        media_type=ctype,
        headers={
            # 타일은 사실상 불변이다. 브라우저와 Cloudflare 모두 오래 들고 있게 한다.
            "Cache-Control": "public, max-age=2592000, s-maxage=2592000, immutable",
            "X-Tile-Cache": "hit" if cached else "miss",
        },
    )


@app.get("/api/tiles/_stats")
async def tile_stats():
    return {"cached": len(_TILE_CACHE), "max": _TILE_CACHE_MAX,
            "inflight": len(_tile_inflight)}


@app.get("/api/diag")
async def diagnose():
    """V-World 연결을 그대로 시험해 결과를 돌려준다.

    배포 환경에서 지적 데이터가 안 나올 때 원인이 네트워크인지, 인증인지,
    도메인인지 구분하려고 둔다. 인증키는 앞뒤 4자만 남겨 가린다.
    """
    key = config.VWORLD_KEY
    masked = f"{len(key)}자 ...{key[-4:]}" if len(key) > 8 else "(없음)"
    out = {"key": masked, "domains": config.VWORLD_DOMAINS, "checks": []}

    async with httpx.AsyncClient(timeout=30.0,
                                 headers={"User-Agent": config.USER_AGENT}) as c:
        # 1) 순수 연결 확인 — 인증키 없이도 응답이 오면 네트워크는 정상
        for label, params in [
            ("data-noauth", {"service": "data", "request": "GetFeature",
                             "data": "LP_PA_CBND_BUBUN", "key": "X", "format": "json",
                             "size": 1, "geomFilter": "BOX(126.93,37.18,126.94,37.19)"}),
        ] + [
            (f"data-domain={d}", {"service": "data", "request": "GetFeature",
                                  "data": "LP_PA_CBND_BUBUN", "key": key, "domain": d,
                                  "format": "json", "geometry": "false", "size": 1,
                                  "crs": "EPSG:4326",
                                  "geomFilter": "BOX(126.938,37.180,126.940,37.182)"})
            for d in config.VWORLD_DOMAINS
        ]:
            rec = {"check": label}
            try:
                r = await c.get(config.VWORLD_DATA_URL, params=params)
                rec["http"] = r.status_code
                try:
                    b = r.json().get("response", {})
                    rec["status"] = b.get("status")
                    rec["error"] = (b.get("error") or {}).get("text", "")[:120]
                except ValueError:
                    rec["body"] = r.text[:120]
            except Exception as exc:  # noqa: BLE001
                rec["exception"] = f"{type(exc).__name__}: {exc}"[:160]
            out["checks"].append(rec)

        # 2) 배경지도 타일
        rec = {"check": "wmts-tile"}
        try:
            r = await c.get(config.VWORLD_TILE_URL.format(
                key=key, layer="Base", z=16, y=25361, x=55917, ext="png"))
            rec["http"] = r.status_code
            rec["bytes"] = len(r.content)
            rec["content_type"] = r.headers.get("content-type", "")
            if r.status_code != 200:
                rec["body"] = r.text[:160]
        except Exception as exc:  # noqa: BLE001
            rec["exception"] = f"{type(exc).__name__}: {exc}"[:160]
        out["checks"].append(rec)

    return out


@app.get("/api/parcels")
async def parcels_preview(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
):
    """지도에 필지 경계를 미리 그려 주기 위한 GeoJSON."""
    box = _parse_bbox(bbox)
    if box.area_km2() > config.MAX_AREA_KM2 * 3:
        raise HTTPException(400, "미리보기 영역이 너무 넓습니다.")
    try:
        items = await vworld.fetch_parcels(box)
    except vworld.VWorldError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — 원인을 삼키지 않는다
        raise HTTPException(502, f"{type(exc).__name__}: {exc}"[:200]) from exc

    features = [{
        "type": "Feature",
        "properties": {"pnu": p["pnu"], "jibun": p["jibun"], "jimok": p["jimok"]},
        "geometry": {"type": "Polygon", "coordinates": [[list(pt) for pt in r]]},
    } for p in items for r in p["rings"][:1]]
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/address")
async def address(lon: float = Query(...), lat: float = Query(...)):
    """지도에서 우클릭한 지점의 지번주소·도로명주소."""
    if not (124 < lon < 132 and 33 < lat < 39):
        raise HTTPException(400, "국내 좌표 범위를 벗어났습니다.")
    try:
        return await vworld.reverse_geocode(lon, lat)
    except vworld.VWorldError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{type(exc).__name__}: {exc}"[:200]) from exc


@app.get("/api/project")
async def project_point(
    lon: float = Query(...), lat: float = Query(...), crs_code: str = Query(..., alias="crs"),
):
    """선택 영역 모서리 좌표를 출력 파일과 똑같은 변환식으로 계산해 준다.

    브라우저의 proj4 정의는 구지적(5174) 데이텀 변환이 서버와 미세하게 다를 수
    있어, 화면에 확정값으로 보여 줄 숫자는 여기서 받아 간다.
    """
    if not crs.is_supported(crs_code):
        raise HTTPException(400, f"지원하지 않는 좌표계입니다: EPSG:{crs_code}")
    x, y = crs.transform_point(lon, lat, crs_code)
    return {"x": x, "y": y, "unit": crs.SUPPORTED[crs_code].unit}


@app.post("/api/jobs")
async def create_job(req: Request):
    body = await req.json()

    try:
        bbox = [float(v) for v in body["bbox"]]
        if len(bbox) != 4:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "bbox 형식이 올바르지 않습니다.") from None

    # CAD에서 부를 때는 도면 좌표(TM)를 그대로 보낸다. 여기서 경위도로 바꾼다.
    bbox_crs = str(body.get("bbox_crs", "4326"))
    if bbox_crs != "4326":
        if not crs.is_supported(bbox_crs):
            raise HTTPException(400, f"지원하지 않는 입력 좌표계입니다: EPSG:{bbox_crs}")
        x0, y0 = crs.to_wgs84(bbox[0], bbox[1], bbox_crs)
        x1, y1 = crs.to_wgs84(bbox[2], bbox[3], bbox_crs)
        bbox = [x0, y0, x1, y1]

    box = BBox(*bbox)
    area = box.area_km2()
    if area <= 0:
        raise HTTPException(400, "영역의 면적이 0입니다.")
    if area > config.MAX_AREA_KM2:
        raise HTTPException(
            400,
            f"선택 영역 {area:.2f} km²가 1회 추출 한도 "
            f"{config.MAX_AREA_KM2:.2f} km²를 초과했습니다.",
        )

    target = str(body.get("crs", crs.DEFAULT))
    if not crs.is_supported(target):
        raise HTTPException(400, f"지원하지 않는 좌표계입니다: EPSG:{target}")

    layers = [str(v) for v in body.get("layers", [])]
    unknown = set(layers) - VALID_LAYERS
    if unknown:
        raise HTTPException(400, f"알 수 없는 레이어: {', '.join(sorted(unknown))}")
    if not layers:
        raise HTTPException(400, "추출할 레이어를 하나 이상 선택하세요.")
    if set(layers) & {"parcel", "pnu"} and not config.VWORLD_KEY:
        raise HTTPException(
            503, "지적 레이어를 받으려면 V-World 인증키가 필요합니다.")

    try:
        job = jobs.create({
            "bbox": bbox,
            "crs": target,
            "layers": layers,
            "options": body.get("options", {}),
            "ip": _client_ip(req),
            # 리습만 bbox_crs 를 보낸다. 웹 화면과 CAD를 이걸로 가른다.
            "source": "cad" if bbox_crs != "4326" else "web",
        })
    except jobs.Busy as exc:
        raise HTTPException(429, str(exc)) from exc
    return JSONResponse({"id": job.id}, status_code=202)


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다. 만료되었을 수 있습니다.")
    return job.as_dict()


@app.get("/api/jobs/{job_id}/download")
async def job_download(job_id: str, request: Request):
    job = jobs.get(job_id)
    if not job or job.state != "done" or not job.path or not job.path.exists():
        raise HTTPException(404, "다운로드할 파일이 없습니다.")
    usage.record_download(job_id, _client_ip(request))
    return FileResponse(job.path, media_type="image/vnd.dxf", filename=job.filename)


def _client_ip(request: Request) -> str | None:
    """Cloudflare 뒤에 있으므로 원래 접속자 IP는 헤더로 온다."""
    for h in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
        v = request.headers.get(h)
        if v:
            return v.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


def _require_admin(request: Request):
    if not config.ADMIN_TOKEN:
        raise HTTPException(
            503, "관리자 암호가 설정되지 않았습니다. .env 에 ADMIN_TOKEN 을 넣으세요.")
    given = (request.headers.get("x-admin-token")
             or request.query_params.get("token") or "")
    if given != config.ADMIN_TOKEN:
        raise HTTPException(401, "관리자 암호가 올바르지 않습니다.")


@app.get("/api/usage")
async def usage_stats(request: Request, days: int = 30):
    _require_admin(request)
    return usage.stats(max(7, min(days, 90)))


# ── 사용 신청 ─────────────────────────────────────────────
@app.post("/api/apply")
async def apply(request: Request):
    """소개 페이지에서 이메일을 남기면 여기로 들어온다."""
    b = await request.json()
    email = (b.get("email") or "").strip()
    if not licensing.valid_email(email):
        raise HTTPException(400, "이메일 주소를 다시 확인해 주세요.")
    a = licensing.apply(
        email=email, name=(b.get("name") or "")[:60],
        company=(b.get("company") or "")[:80], memo=(b.get("memo") or "")[:300],
        ip=_client_ip(request))
    return {"ok": True, "already": a.get("already", False)}


# ── 라이선스 검증 (리습이 부른다) ─────────────────────────
@app.post("/api/license/check")
async def license_check(request: Request):
    b = await request.json()
    return licensing.check((b.get("key") or ""), (b.get("machine") or "")[:120])


# ── 관리자: 신청자와 라이선스 ─────────────────────────────
@app.get("/api/admin/applicants")
async def admin_applicants(request: Request):
    _require_admin(request)
    return {"applicants": licensing.list_applicants(),
            "mail_ready": mailer.configured(),
            "bank": config.BANK_INFO, "demo_days": config.DEMO_DAYS}


@app.post("/api/admin/send")
async def admin_send(request: Request):
    """신청자에게 발급키와 사용법을 메일로 보낸다. kind: demo | full"""
    _require_admin(request)
    b = await request.json()
    email = (b.get("email") or "").strip().lower()
    kind = "full" if b.get("kind") == "full" else "demo"
    if not licensing.valid_email(email):
        raise HTTPException(400, "이메일 주소가 올바르지 않습니다.")
    if not mailer.configured():
        raise HTTPException(503, "메일 계정이 설정되지 않았습니다.")

    lic = licensing.issue(email, kind=kind, note=b.get("note") or "")
    name = (b.get("name") or "").strip()
    subject, body = (mailer.full_body(lic["key"], name) if kind == "full"
                     else mailer.demo_body(lic["key"], name))

    # 배포 파일이 있으면 첨부한다. 없으면 본문만 보낸다.
    attach = []
    pkg = WEB / "download" / "CADMAP-setup.zip"
    if pkg.exists():
        attach.append((pkg.name, pkg.read_bytes(), "application/zip"))

    try:
        await asyncio.to_thread(mailer.send, email, subject, body, attach)
    except mailer.MailError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "key": lic["key"], "kind": kind,
            "attached": bool(attach)}


@app.post("/api/admin/license/{key}/{action}")
async def admin_license(key: str, action: str, request: Request):
    _require_admin(request)
    fn = {"upgrade": licensing.upgrade,
          "revoke": lambda k: licensing.revoke(k, True),
          "unrevoke": lambda k: licensing.revoke(k, False),
          "reset-machine": licensing.reset_machine}.get(action)
    if not fn:
        raise HTTPException(400, "알 수 없는 동작입니다.")
    out = fn(key)
    if not out:
        raise HTTPException(404, "발급키를 찾을 수 없습니다.")
    return out


@app.delete("/api/admin/applicants/{aid}")
async def admin_applicant_delete(aid: int, request: Request):
    _require_admin(request)
    if not licensing.delete_applicant(aid):
        raise HTTPException(404, "신청자를 찾을 수 없습니다.")
    return {"ok": True}


# ── 공지사항 ──────────────────────────────────────────────
@app.get("/api/notices")
async def notices_public(all: int = 0):
    """all=0 이면 접속 시 팝업으로 띄울 것만, all=1 이면 게시판용 전체."""
    return {"notices": notices.active(popup_only=not all)}


@app.get("/api/admin/notices")
async def notices_list(request: Request):
    _require_admin(request)
    return {"notices": notices.list_all()}


@app.post("/api/admin/notices")
async def notices_create(request: Request):
    _require_admin(request)
    b = await request.json()
    title = (b.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "제목을 입력하세요.")
    return notices.create(
        title=title, body=b.get("body") or "", kind=b.get("kind") or "info",
        popup=bool(b.get("popup", True)),
        starts=b.get("starts"), ends=b.get("ends"))


@app.patch("/api/admin/notices/{nid}")
async def notices_update(nid: int, request: Request):
    _require_admin(request)
    b = await request.json()
    out = notices.update(nid, **b)
    if not out:
        raise HTTPException(404, "공지를 찾을 수 없습니다.")
    return out


@app.delete("/api/admin/notices/{nid}")
async def notices_delete(nid: int, request: Request):
    _require_admin(request)
    if not notices.delete(nid):
        raise HTTPException(404, "공지를 찾을 수 없습니다.")
    return {"ok": True}


def _asset_version() -> str:
    """정적 파일이 바뀌면 값이 달라지는 짧은 해시.

    Cloudflare와 브라우저가 js/css를 몇 시간씩 붙들고 있어서, 코드를 고쳐도
    옛 파일이 그대로 나가는 일이 있었다. 주소에 이 값을 붙여 파일이 바뀌면
    주소도 바뀌게 한다. 덕분에 캐시는 그대로 길게 두고도 갱신이 즉시 반영된다.
    """
    h = hashlib.sha1()
    for name in sorted(("app.js", "style.css", "logo.svg",
                        "index.html", "admin.html", "cad.html")):
        f = WEB / name
        if f.exists():
            st = f.stat()
            h.update(f"{name}:{st.st_mtime_ns}:{st.st_size}".encode())
    return h.hexdigest()[:10]


def _serve_page(name: str) -> Response:
    """페이지를 내보내면서 정적 자원 주소에 버전을 붙인다."""
    v = _asset_version()
    html = (WEB / name).read_text(encoding="utf-8")
    for asset in ("app.js", "style.css", "logo.svg"):
        html = html.replace(f'"{asset}"', f'"{asset}?v={v}"')
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        # 페이지 자체는 캐시하지 않는다. 안에 든 버전이 최신이어야 하기 때문이다.
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/")
async def index_page():
    return _serve_page("index.html")


@app.get("/cad")
async def cad_page():
    return _serve_page("cad.html")


# ── 리습 배포 ─────────────────────────────────────────────
DIST = WEB / "dist"


def _version_info() -> dict:
    f = DIST / "version.json"
    if not f.exists():
        return {}
    try:
        import json
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/api/cad/version")
async def cad_version(request: Request, current: str = "", key: str = ""):
    """리습이 시작할 때 하루 한 번 부른다. 새 버전이 있으면 알려 준다.

    발급키를 함께 보내면 라이선스 상태도 같이 돌려주므로, 리습이 요청을
    한 번만 하고도 업데이트와 사용 가능 여부를 동시에 알 수 있다.
    """
    v = _version_info()
    latest = v.get("version", "")
    files = v.get("files") or {}
    # 판 번호를 주소에 붙인다. Cloudflare 는 주소가 같으면 네 시간을 캐시하므로,
    # 이것이 없으면 새 판을 올려도 한동안 옛 파일이 내려간다.
    tag = f"?v={latest}" if latest else ""
    out = {
        "version": latest,
        "date": v.get("date", ""),
        "notice": v.get("notice", ""),
        "url": files.get("lisp", "/dist/CADMAP.lsp") + tag,
        "installer": files.get("installer", "/dist/install.exe") + tag,
        "site": config.SITE_URL,
        "update": bool(latest and current and _ver(latest) > _ver(current)),
        "required": bool(v.get("min_version") and current
                         and _ver(current) < _ver(v["min_version"])),
        "available": (DIST / "CADMAP.lsp").exists(),
        "installer_ready": (DIST / "install.exe").exists(),
    }
    if key:
        out["license"] = licensing.check(key, (request.headers.get("x-machine") or "")[:120])
    return out


def _ver(s: str) -> tuple:
    """'1.10.2' 를 비교 가능한 형태로. 자리수가 달라도 올바르게 비교된다."""
    parts = []
    for chunk in str(s).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (4 - len(parts)))[:4]


@app.get("/dist/{name:path}")
async def dist_file(name: str):
    """배포 파일. 폴더에 복사만 하면 바로 받아진다."""
    if not name or ".." in name or name.startswith(("/", "\\")):
        raise HTTPException(404, "없는 파일입니다.")
    f = (DIST / name).resolve()
    if not str(f).startswith(str(DIST.resolve())) or not f.is_file():
        raise HTTPException(404, "없는 파일입니다.")
    # 버전 파일은 절대 캐시하면 안 된다. 나머지는 짧게만 둔다.
    cache = ("no-cache, must-revalidate" if f.name == "version.json"
             else "public, max-age=300")
    # 리습은 옛 AutoCAD 도 읽도록 cp949 로 배포한다. 그대로 알려 줘야
    # 브라우저에서 열어 봐도 한글이 깨지지 않는다.
    media = {"json": "application/json", "lsp": "text/plain; charset=euc-kr",
             "mnu": "text/plain; charset=utf-8", "exe": "application/octet-stream",
             "zip": "application/zip"}.get(f.suffix.lstrip(".").lower(),
                                           "application/octet-stream")
    return FileResponse(f, media_type=media, filename=f.name,
                        headers={"Cache-Control": cache})


@app.get("/admin")
async def admin_page():
    return _serve_page("admin.html")


def _parse_bbox(raw: str) -> BBox:
    try:
        parts = [float(v) for v in raw.split(",")]
        if len(parts) != 4:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "bbox는 minLon,minLat,maxLon,maxLat 형식입니다.") from None
    return BBox(*parts)


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
