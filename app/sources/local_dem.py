"""국토지리정보원 수치표고모델을 파일에서 읽는다.

국토정보플랫폼(map.ngii.go.kr)은 오픈API가 없고 로그인 후 도엽 단위로 내려받는
방식이라 자동 조회가 불가능하다. 그래서 한 번 받아 둔 파일을 `dem/` 폴더에 넣어
두면 해당 지역 요청에서 자동으로 골라 쓰도록 했다.

지원 형식은 GDAL이 읽는 래스터 전부다(.img .tif .asc .adf 등). 좌표계는 파일에
기록된 것을 그대로 쓰되, 국토지리정보원 배포본처럼 좌표계 정보가 빠진 파일은
`.env`의 `DEM_FALLBACK_CRS`로 지정한다.
"""
import json
import math
import threading
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject, transform_bounds

from .. import config
from ..geom import BBox

SUFFIXES = {".img", ".tif", ".tiff", ".asc", ".adf", ".dem", ".bil", ".vrt"}
_lock = threading.Lock()
_index = None


class DemFile:
    def __init__(self, path, crs, bounds_wgs84, res_m, nodata):
        self.path = Path(path)
        self.crs = crs
        self.bounds = bounds_wgs84          # (minlon, minlat, maxlon, maxlat)
        self.res_m = res_m
        self.nodata = nodata

    def covers(self, box: BBox, need=0.999):
        """요청 영역이 이 파일 안에 얼마나 들어오는지 비율로 판단."""
        w = min(self.bounds[2], box.max_lon) - max(self.bounds[0], box.min_lon)
        h = min(self.bounds[3], box.max_lat) - max(self.bounds[1], box.min_lat)
        if w <= 0 or h <= 0:
            return 0.0
        area = (box.max_lon - box.min_lon) * (box.max_lat - box.min_lat)
        return (w * h) / area if area else 0.0

    def as_dict(self):
        return {"path": str(self.path), "crs": self.crs, "bounds": self.bounds,
                "res_m": self.res_m, "nodata": self.nodata,
                "mtime": self.path.stat().st_mtime}


def _scan():
    """DEM 폴더를 훑어 각 파일의 범위와 해상도를 색인한다."""
    out = []
    root = config.DEM_DIR
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            continue
        try:
            with rasterio.open(p) as ds:
                crs = ds.crs
                if crs is None:
                    if not config.DEM_FALLBACK_CRS:
                        print(f"[dem] 좌표계 없음, 건너뜀: {p.name} "
                              f"(DEM_FALLBACK_CRS를 지정하세요)")
                        continue
                    crs = rasterio.crs.CRS.from_string(config.DEM_FALLBACK_CRS)
                b = transform_bounds(crs, "EPSG:4326", *ds.bounds, densify_pts=21)
                # 픽셀 크기를 미터로 환산 (지리좌표계면 도→미터)
                rx, ry = abs(ds.transform.a), abs(ds.transform.e)
                if crs.is_geographic:
                    midlat = (b[1] + b[3]) / 2
                    rx *= 111320 * math.cos(math.radians(midlat))
                    ry *= 110540
                out.append(DemFile(p, crs.to_string(), tuple(b),
                                   round(min(rx, ry), 3), ds.nodata))
        except (rasterio.RasterioIOError, ValueError) as exc:
            print(f"[dem] 읽기 실패: {p.name} — {exc}")
    return out


def index(refresh=False):
    """색인을 만들어 캐시한다. 파일이 바뀌면 다시 훑는다."""
    global _index
    with _lock:
        if _index is not None and not refresh:
            return _index
        cache = config.DEM_DIR / ".index.json"
        files = _scan()
        _index = files
        try:
            config.DEM_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps([f.as_dict() for f in files],
                                        ensure_ascii=False, indent=1),
                             encoding="utf-8")
        except OSError:
            pass
        return _index


def pick(box: BBox):
    """요청 영역을 가장 잘 덮으면서 해상도가 가장 좋은 파일을 고른다."""
    cands = [(f.covers(box), f) for f in index()]
    cands = [(c, f) for c, f in cands if c > 0.05]
    if not cands:
        return None, 0.0
    # 완전히 덮는 것 우선, 그 다음 해상도가 좋은 것
    cands.sort(key=lambda t: (-(t[0] >= 0.999), t[1].res_m, -t[0]))
    cov, best = cands[0]
    return best, cov


def load(box: BBox):
    """로컬 DEM에서 경위도 격자를 만든다. 쓸 파일이 없으면 None.

    returns (grid, lons, lats, meta) — AWS 경로와 같은 형태.
    """
    f, cov = pick(box)
    if f is None:
        return None

    # 원자료 해상도에 맞춰 출력 격자 크기를 정한다.
    step_m = max(1.0, f.res_m)
    ncols = int(box.width_m() / step_m) + 1
    nrows = int(box.height_m() / step_m) + 1
    ncols = max(8, min(ncols, 2400))
    nrows = max(8, min(nrows, 2400))

    lons = np.linspace(box.min_lon, box.max_lon, ncols)
    lats = np.linspace(box.min_lat, box.max_lat, nrows)

    dst = np.full((nrows, ncols), np.nan, dtype=np.float32)
    # 북쪽이 위인 표준 배치로 만든 뒤 마지막에 뒤집는다.
    dst_transform = rasterio.transform.from_bounds(
        box.min_lon, box.min_lat, box.max_lon, box.max_lat, ncols, nrows)

    with rasterio.open(f.path) as ds:
        src_crs = ds.crs or rasterio.crs.CRS.from_string(config.DEM_FALLBACK_CRS)
        reproject(
            source=rasterio.band(ds, 1),
            destination=dst,
            src_transform=ds.transform,
            src_crs=src_crs,
            src_nodata=ds.nodata,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    grid = dst[::-1, :]                      # 남→북 오름차순으로
    valid = np.isfinite(grid)
    if valid.sum() < grid.size * 0.5:
        return None                          # 구멍이 너무 많으면 쓰지 않는다
    if not valid.all():
        grid = _fill_holes(grid, valid)

    meta = {
        "source": "local",
        "file": f.path.name,
        "grid_m": round(step_m, 2),
        "coverage": round(cov, 3),
        "crs": f.crs,
    }
    return grid.astype(np.float32), lons, lats, meta


def _fill_holes(grid, valid):
    """작은 결측은 전체 평균으로 메운다. 등고선이 끊기는 것보다 낫다."""
    filled = grid.copy()
    filled[~valid] = float(np.nanmean(grid[valid]))
    return filled


def describe():
    """설정 화면에 보여 줄 색인 요약."""
    files = index()
    if not files:
        return {"count": 0, "files": []}
    return {
        "count": len(files),
        "files": [{"name": f.path.name, "grid_m": f.res_m,
                   "crs": f.crs, "bounds": [round(v, 5) for v in f.bounds]}
                  for f in files[:50]],
    }
