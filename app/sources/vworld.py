"""V-World 연속지적도(LP_PA_CBND_BUBUN) 조회.

Data API는 1회 응답이 1000건으로 제한되므로 total을 보고 페이징한다.
반환 좌표는 EPSG:4326 경위도이며, 좌표계 변환은 호출한 쪽에서 한다.
"""
import re

import httpx

from .. import config
from ..geom import BBox

LAYER = "LP_PA_CBND_BUBUN"

# "251-1전" 처럼 지번 뒤에 지목이 붙어 온다.
_JIBUN = re.compile(r"^(산?\s*[\d\-]+)\s*(.*)$")


class VWorldError(RuntimeError):
    pass


def _parse_jibun(raw: str):
    raw = (raw or "").strip()
    m = _JIBUN.match(raw)
    if not m:
        return raw, ""
    return m.group(1).strip(), m.group(2).strip()


async def fetch_parcels(box: BBox, progress=None):
    """영역에 걸치는 필지 목록을 반환한다.

    각 항목: {"pnu", "jibun", "jimok", "rings": [[(lon, lat), ...], ...]}
    """
    if not config.VWORLD_KEY:
        raise VWorldError(
            "V-World 인증키가 없습니다. vworld.kr에서 발급받아 .env의 VWORLD_KEY에 넣으세요."
        )

    out = []
    page = 1
    total = None
    # 등록된 도메인을 찾으면 그 뒤로는 계속 그것만 쓴다.
    domains = list(config.VWORLD_DOMAINS)
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        while page <= config.VWORLD_MAX_PAGES:
            body, domains = await _get_page(client, box, page, domains)
            status = body.get("status")

            if status == "NOT_FOUND":
                break
            if status != "OK":
                msg = body.get("error", {}).get("text") or status or "알 수 없는 오류"
                raise VWorldError(f"V-World 응답 오류: {msg}")

            fc = body.get("result", {}).get("featureCollection", {})
            feats = fc.get("features", [])
            if not feats:
                break

            for f in feats:
                parsed = _feature_to_parcel(f)
                if parsed:
                    out.append(parsed)

            if total is None:
                try:
                    total = int(body.get("record", {}).get("total", 0))
                except (TypeError, ValueError):
                    total = len(feats)
            if progress and total:
                progress(min(1.0, len(out) / total))

            if len(out) >= (total or 0) or len(feats) < config.VWORLD_PAGE_SIZE:
                break
            page += 1

    return out


ADDRESS_URL = "https://api.vworld.kr/req/address"


async def reverse_geocode(lon: float, lat: float) -> dict:
    """좌표 → 주소. 지번주소와 도로명주소를 함께 돌려준다.

    Data API와 마찬가지로 도메인 검사를 받으므로 등록된 도메인을 찾을 때까지
    순서대로 시도한다.
    """
    if not config.VWORLD_KEY:
        raise VWorldError("V-World 인증키가 없습니다.")

    last = ""
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        for dom in config.VWORLD_DOMAINS:
            r = await client.get(ADDRESS_URL, params={
                "service": "address", "request": "getAddress", "version": "2.0",
                "crs": "epsg:4326", "point": f"{lon},{lat}", "format": "json",
                "type": "both", "zipcode": "true", "simple": "false",
                "key": config.VWORLD_KEY, "domain": dom,
            })
            r.raise_for_status()
            body = r.json().get("response", {})
            status = body.get("status")

            if status == "OK":
                out = {"parcel": None, "road": None, "zipcode": None}
                for item in body.get("result", []) or []:
                    kind = item.get("type")
                    if kind in ("parcel", "road"):
                        out[kind] = item.get("text")
                    out["zipcode"] = out["zipcode"] or item.get("zipcode")
                return out
            if status == "NOT_FOUND":
                return {"parcel": None, "road": None, "zipcode": None}

            last = (body.get("error") or {}).get("text") or status or ""
            if "인증키" not in last:
                break

    raise VWorldError(f"주소를 가져오지 못했습니다: {last or '알 수 없는 오류'}")


async def _get_page(client, box, page, domains, layer=LAYER):
    """등록된 도메인을 찾을 때까지 순서대로 시도한다.

    성공한 도메인을 목록 맨 앞으로 올려 돌려주므로 다음 페이지부터는 한 번에 된다.
    """
    last = None
    for i, dom in enumerate(domains):
        params = {
            "service": "data",
            "request": "GetFeature",
            "data": layer,
            "key": config.VWORLD_KEY,
            "domain": dom,
            "format": "json",
            "geometry": "true",
            "attribute": "true",
            "crs": "EPSG:4326",
            "geomFilter": "BOX({},{},{},{})".format(*box.as_tuple()),
            "size": config.VWORLD_PAGE_SIZE,
            "page": page,
        }
        r = await client.get(config.VWORLD_DATA_URL, params=params)
        r.raise_for_status()
        body = r.json().get("response", {})
        last = body
        if body.get("status") in ("OK", "NOT_FOUND"):
            if i:
                domains = [dom] + [d for d in domains if d != dom]
            return body, domains
        # 도메인 문제가 아니면 다른 도메인으로 재시도해도 소용없다
        if "인증키" not in (body.get("error", {}).get("text") or ""):
            return body, domains
    return last or {}, domains


def _feature_to_parcel(feature):
    geom = feature.get("geometry") or {}
    props = feature.get("properties") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None

    if gtype == "Polygon":
        polys = [coords]
    elif gtype == "MultiPolygon":
        polys = coords
    else:
        return None

    rings = []
    for poly in polys:
        if not poly:
            continue
        # 외곽 링만 사용한다. 내부 구멍(섬 필지)은 별도 폐합 폴리라인으로 넣는다.
        for ring in poly:
            pts = [(float(p[0]), float(p[1])) for p in ring if len(p) >= 2]
            if len(pts) >= 3:
                rings.append(pts)

    if not rings:
        return None

    jibun, jimok = _parse_jibun(props.get("jibun", ""))
    return {
        "pnu": props.get("pnu", ""),
        "jibun": jibun,
        "jimok": jimok,
        "rings": rings,
    }


# ── 도시계획·지역지구 조회 ─────────────────────────────────────
async def fetch_shapes(box: BBox, layer: str, progress=None) -> list[dict]:
    """레이어 하나를 통째로 받아 [{props, rings}] 로 돌려준다.

    지적도와 달리 종류가 수십 가지라 속성을 그대로 넘긴다. 어느 칸이
    이름인지는 부르는 쪽(layers.py)이 안다.

    도형은 대부분 MultiPolygon 이다. 도시계획선은 그 면의 테두리이므로
    바깥·안쪽 고리를 모두 그대로 담아 준다.
    """
    if not config.VWORLD_KEY:
        raise VWorldError("V-World 인증키가 없습니다.")

    out: list[dict] = []
    page = 1
    total = None
    domains = list(config.VWORLD_DOMAINS)

    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        while page <= config.VWORLD_MAX_PAGES:
            body, domains = await _get_page(client, box, page, domains, layer)
            status = body.get("status")

            # 그 지역에 자료가 없는 것은 잘못이 아니다. 빈 채로 넘어간다.
            if status == "NOT_FOUND":
                break
            if status != "OK":
                msg = body.get("error", {}).get("text") or status or "알 수 없는 오류"
                raise VWorldError(f"{layer}: {msg}")

            feats = (body.get("result", {}).get("featureCollection", {})
                     .get("features", []))
            if not feats:
                break

            for f in feats:
                parsed = _shape_of(f)
                if parsed:
                    out.append(parsed)

            if total is None:
                try:
                    total = int(body.get("record", {}).get("total", 0))
                except (TypeError, ValueError):
                    total = len(feats)
            if progress and total:
                progress(min(1.0, len(out) / total))

            if len(out) >= (total or 0) or len(feats) < config.VWORLD_PAGE_SIZE:
                break
            page += 1

    return out


def _shape_of(f: dict) -> dict | None:
    """도형 하나를 {props, rings, closed, points} 로 편다."""
    geom = f.get("geometry") or {}
    kind = str(geom.get("type") or "")
    rings = _rings_of(geom)
    points = _points_of(geom)
    if not rings and not points:
        return None
    return {"props": f.get("properties") or {},
            "rings": rings, "points": points,
            # 선 자료(도로 중심선 등)를 닫아 버리면 엉뚱한 면이 된다.
            "closed": "Line" not in kind}


def _points_of(geom: dict) -> list[tuple[float, float]]:
    kind = geom.get("type")
    co = geom.get("coordinates") or []
    if kind == "Point" and len(co) >= 2:
        return [(float(co[0]), float(co[1]))]
    if kind == "MultiPoint":
        return [(float(p[0]), float(p[1])) for p in co
                if isinstance(p, (list, tuple)) and len(p) >= 2]
    return []


def _rings_of(geom: dict) -> list[list[tuple[float, float]]]:
    """Polygon · MultiPolygon · LineString 을 고리 목록으로 편다."""
    kind = geom.get("type")
    co = geom.get("coordinates") or []
    rings: list[list[tuple[float, float]]] = []

    def add(seq):
        pts = [(float(p[0]), float(p[1])) for p in seq
               if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(pts) >= 2:
            rings.append(pts)

    if kind == "Polygon":
        for r in co:
            add(r)
    elif kind == "MultiPolygon":
        for poly in co:
            for r in poly:
                add(r)
    elif kind == "LineString":
        add(co)
    elif kind == "MultiLineString":
        for r in co:
            add(r)
    return rings


async def props_at(client, lon: float, lat: float, layer: str,
                   domain: str | None = None) -> list[dict]:
    """그 점이 드는 도형의 속성만 가져온다. 도형은 받지 않는다.

    토지이용계획은 "이 자리가 무엇에 걸리는가"만 알면 되므로, 도형을
    빼고 속성만 받으면 훨씬 가볍다.
    """
    params = {
        "service": "data", "request": "GetFeature", "data": layer,
        "key": config.VWORLD_KEY,
        "domain": domain or (config.VWORLD_DOMAINS[0] if config.VWORLD_DOMAINS else ""),
        "format": "json", "crs": "EPSG:4326", "size": 10,
        "geometry": "false", "attribute": "true",
        "geomFilter": f"POINT({lon} {lat})",
    }
    try:
        r = await client.get(config.VWORLD_DATA_URL, params=params)
        body = r.json().get("response", {})
    except Exception:                       # noqa: BLE001 — 하나 실패해도 나머지는 본다
        return []
    if body.get("status") != "OK":
        return []
    return [f.get("properties") or {} for f in
            body.get("result", {}).get("featureCollection", {})
                .get("features", [])]


WFS_URL = "https://api.vworld.kr/req/wfs"


async def fetch_wfs(box: BBox, typename: str, progress=None) -> list[dict]:
    """Data API 에 없는 레이어는 WFS 로 받는다. 형식만 다를 뿐 같은 벡터다.

    한 번에 1000개까지만 받는다. 과속방지턱처럼 촘촘한 자료는 넘칠 수
    있는데, 그때는 부르는 쪽이 경고를 남긴다.
    """
    if not config.VWORLD_KEY:
        raise VWorldError("V-World 인증키가 없습니다.")
    params = {
        "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0",
        "TYPENAME": typename, "KEY": config.VWORLD_KEY,
        "DOMAIN": config.VWORLD_DOMAINS[0] if config.VWORLD_DOMAINS else "",
        "MAXFEATURES": 1000, "SRSNAME": "EPSG:4326",
        "OUTPUT": "application/json",
        # WFS 1.1.0 의 EPSG:4326 은 위도가 먼저다. 경도부터 넣으면 빈손이 온다.
        "BBOX": "{1},{0},{3},{2},EPSG:4326".format(*box.as_tuple()),
    }
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as c:
        r = await c.get(WFS_URL, params=params)
    try:
        body = r.json()
    except ValueError:
        return []
    out = []
    for f in body.get("features") or []:
        parsed = _shape_of(f)
        if parsed:
            out.append(parsed)
    if progress:
        progress(1.0)
    return out
