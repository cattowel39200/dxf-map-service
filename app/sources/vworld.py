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


async def _get_page(client, box, page, domains):
    """등록된 도메인을 찾을 때까지 순서대로 시도한다.

    성공한 도메인을 목록 맨 앞으로 올려 돌려주므로 다음 페이지부터는 한 번에 된다.
    """
    last = None
    for i, dom in enumerate(domains):
        params = {
            "service": "data",
            "request": "GetFeature",
            "data": LAYER,
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
