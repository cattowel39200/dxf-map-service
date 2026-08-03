"""OpenStreetMap Overpass에서 건물·도로·수계를 가져온다.

수치지형도는 국토지리정보원에 도엽 단위로 신청해야 해 자동화가 불가능하다.
그 자리를 OSM으로 메운다. 시가지는 촘촘하지만 농산간 지역은 누락이 있을 수 있다.
"""
import asyncio

import httpx

from .. import config
from ..geom import BBox

_QUERY = """
[out:json][timeout:{timeout}];
(
  way["building"]({s},{w},{n},{e});
  way["highway"]({s},{w},{n},{e});
  way["waterway"~"^(river|stream|canal|ditch|drain)$"]({s},{w},{n},{e});
  way["natural"="water"]({s},{w},{n},{e});
  way["landuse"="reservoir"]({s},{w},{n},{e});
);
out geom;
"""


class OverpassError(RuntimeError):
    pass


async def fetch_features(box: BBox):
    """{"building": [...], "road": [...], "water": [...]} 를 반환한다.

    각 항목: {"pts": [(lon, lat), ...], "closed": bool, "name": str}
    """
    q = _QUERY.format(timeout=int(config.HTTP_TIMEOUT),
                      s=box.min_lat, w=box.min_lon, n=box.max_lat, e=box.max_lon)
    data = await _post_with_fallback(q)

    out = {"building": [], "road": [], "water": []}
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        pts = [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]
        if len(pts) < 2:
            continue
        tags = el.get("tags") or {}
        kind = _classify(tags)
        if not kind:
            continue
        closed = len(pts) > 3 and abs(pts[0][0] - pts[-1][0]) < 1e-9 \
            and abs(pts[0][1] - pts[-1][1]) < 1e-9
        out[kind].append({
            "pts": pts[:-1] if closed else pts,
            "closed": closed,
            "name": tags.get("name", ""),
        })
    return out


async def _post_with_fallback(query: str):
    """미러를 순서대로 시도한다. 붐비는 인스턴스는 504/429를 즉시 돌려준다."""
    errors = []
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT + 20,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        for url in config.OVERPASS_URLS:
            for attempt in range(2):
                try:
                    r = await client.post(url, data={"data": query})
                    if r.status_code in (429, 502, 503, 504):
                        errors.append(f"{_host(url)} HTTP {r.status_code}")
                        if attempt == 0:
                            await asyncio.sleep(2.0)
                            continue
                        break
                    r.raise_for_status()
                    return r.json()
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(f"{_host(url)} {exc.__class__.__name__}")
                    break
    raise OverpassError(
        "OSM 서버에서 지형지물을 받지 못했습니다 (" + ", ".join(errors[:4]) + "). "
        "공용 서버가 붐비는 상태이니 잠시 후 다시 시도하세요."
    )


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def _classify(tags):
    if "building" in tags:
        return "building"
    if tags.get("natural") == "water" or tags.get("landuse") == "reservoir" \
            or "waterway" in tags:
        return "water"
    if "highway" in tags:
        # 보행 전용 경로는 도면 노이즈라 뺀다.
        if tags["highway"] in ("footway", "path", "steps", "cycleway", "corridor"):
            return None
        return "road"
    return None
