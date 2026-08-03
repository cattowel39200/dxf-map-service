"""출력 좌표계 정의와 변환.

프론트엔드의 드롭다운과 이 표가 1:1로 대응한다. 변환은 pyproj가 EPSG 공식
정의를 사용하므로 구지적(5174)도 근사식이 아닌 등록된 변환식을 탄다.
"""
from functools import lru_cache

from pyproj import CRS as PyCRS
from pyproj import Transformer

WGS84 = "EPSG:4326"


class CrsDef:
    def __init__(self, code, name, group, ellipsoid, origin, unit="m", note=""):
        self.code = code
        self.name = name
        self.group = group
        self.ellipsoid = ellipsoid
        self.origin = origin
        self.unit = unit
        self.note = note

    def as_dict(self):
        d = PyCRS.from_epsg(int(self.code))
        return {
            "code": self.code,
            "name": self.name,
            "group": self.group,
            "ellipsoid": self.ellipsoid,
            "origin": self.origin,
            "unit": self.unit,
            "note": self.note,
            "projection": "Geographic" if d.is_geographic else "Transverse Mercator",
            "wkt_name": d.name,
        }


SUPPORTED = {
    "5186": CrsDef("5186", "중부원점 (세계측지계)", "세계측지계 (GRS80) — 현행",
                   "GRS80", "127°00′00″ / 38°N"),
    "5185": CrsDef("5185", "서부원점 (세계측지계)", "세계측지계 (GRS80) — 현행",
                   "GRS80", "125°00′00″ / 38°N"),
    "5187": CrsDef("5187", "동부원점 (세계측지계)", "세계측지계 (GRS80) — 현행",
                   "GRS80", "129°00′00″ / 38°N"),
    "5188": CrsDef("5188", "동해(울릉)원점 (세계측지계)", "세계측지계 (GRS80) — 현행",
                   "GRS80", "131°00′00″ / 38°N"),
    "5179": CrsDef("5179", "UTM-K 단일원점", "세계측지계 (GRS80) — 현행",
                   "GRS80", "127°30′00″ / 38°N"),
    "5174": CrsDef("5174", "중부원점 (구 지적)", "구 지적 (Bessel 1841)",
                   "Bessel 1841", "127°00′10.405″ / 38°N",
                   note="구 지적 성과. 세계측지계와 약 300 m 차이가 나며 "
                        "지역별 국지 보정이 반영되지 않아 인허가 도면에는 권장하지 않는다."),
    "32652": CrsDef("32652", "UTM Zone 52N", "국제 표준", "WGS84", "129°00′00″ / 0°"),
    "4326": CrsDef("4326", "WGS84 경위도", "국제 표준", "WGS84", "—", unit="degree"),
}

DEFAULT = "5186"


def is_supported(code: str) -> bool:
    return str(code) in SUPPORTED


@lru_cache(maxsize=32)
def _transformer(code: str) -> Transformer:
    # always_xy=True → 입출력을 (경도, 위도) / (X=동, Y=북) 순서로 고정한다.
    return Transformer.from_crs(WGS84, f"EPSG:{code}", always_xy=True)


def transform_ring(ring, code: str):
    """[(lon, lat), ...] → [(x, y), ...]"""
    tr = _transformer(str(code))
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    xs, ys = tr.transform(lons, lats)
    return list(zip(xs, ys))


def transform_point(lon: float, lat: float, code: str):
    return _transformer(str(code)).transform(lon, lat)


@lru_cache(maxsize=32)
def _inverse(code: str) -> Transformer:
    return Transformer.from_crs(f"EPSG:{code}", WGS84, always_xy=True)


def to_wgs84(x: float, y: float, code: str):
    """투영좌표 → 경위도. CAD 도면 좌표로 영역을 받을 때 쓴다."""
    if str(code) == "4326":
        return x, y
    return _inverse(str(code)).transform(x, y)


def catalog():
    """프론트엔드 드롭다운용 그룹별 목록."""
    groups = {}
    for c in SUPPORTED.values():
        groups.setdefault(c.group, []).append(c.as_dict())
    return [{"group": g, "items": items} for g, items in groups.items()]
