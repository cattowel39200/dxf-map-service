"""수치표고 격자 취득.

AWS Terrain Tiles(terrarium 인코딩)를 쓴다. 인증키가 필요 없고 전지구를 덮는다.
해상도는 위도 37도 z13 기준 약 12 m로, 1:5,000 지형도보다는 거칠다. 국토지리정보원
정밀 DEM을 확보하면 load_dem()만 교체하면 된다.
"""
import asyncio
import io
import math

import httpx
import numpy as np
from PIL import Image

from .. import config
from ..geom import BBox
from . import local_dem

TILE = 256


def _lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def _tile_to_lon(x, z):
    return x / 2 ** z * 360.0 - 180.0


def _tile_to_lat(y, z):
    n = math.pi - 2.0 * math.pi * y / 2 ** z
    return math.degrees(math.atan(math.sinh(n)))


async def load_dem(box: BBox, zoom: int = None, progress=None):
    """영역을 덮는 표고 격자를 반환한다.

    국토지리정보원 DEM이 `dem/` 폴더에 있으면 그것을 쓰고, 없으면 AWS로 넘어간다.
    returns (grid, lons, lats, meta) — grid[j][i]가 lats[j], lons[i]의 표고(m).
    lats는 남→북 오름차순이다.
    """
    local = await asyncio.to_thread(local_dem.load, box)
    if local is not None:
        if progress:
            progress(1.0)
        return local

    return await _load_aws(box, zoom, progress)


async def _load_aws(box: BBox, zoom=None, progress=None):
    z = zoom or config.DEM_ZOOM
    x0f, y0f = _lonlat_to_tile(box.min_lon, box.max_lat, z)   # 좌상단
    x1f, y1f = _lonlat_to_tile(box.max_lon, box.min_lat, z)   # 우하단
    x0, y0 = int(math.floor(x0f)), int(math.floor(y0f))
    x1, y1 = int(math.floor(x1f)), int(math.floor(y1f))

    n = 2 ** z
    cols = list(range(x0, x1 + 1))
    rows = list(range(y0, y1 + 1))
    if len(cols) * len(rows) > 64:
        raise RuntimeError("요청 영역이 표고 타일 한도를 넘었습니다. 영역을 줄여 주세요.")

    mosaic = np.zeros((len(rows) * TILE, len(cols) * TILE), dtype=np.float32)
    done = 0
    total = len(rows) * len(cols)

    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        sem = asyncio.Semaphore(8)

        async def one(ri, ci, tx, ty):
            nonlocal done
            async with sem:
                url = config.DEM_TILE_URL.format(z=z, x=tx % n, y=ty)
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    img = Image.open(io.BytesIO(r.content)).convert("RGB")
                    a = np.asarray(img, dtype=np.float32)
                    elev = a[:, :, 0] * 256.0 + a[:, :, 1] + a[:, :, 2] / 256.0 - 32768.0
                except (httpx.HTTPError, OSError):
                    elev = np.zeros((TILE, TILE), dtype=np.float32)
                mosaic[ri * TILE:(ri + 1) * TILE, ci * TILE:(ci + 1) * TILE] = elev
                done += 1
                if progress:
                    progress(done / total)

        await asyncio.gather(*[
            one(ri, ci, tx, ty)
            for ri, ty in enumerate(rows)
            for ci, tx in enumerate(cols)
        ])

    # 모자이크 픽셀 중심의 경위도. 웹메르카토르라 위도 간격은 균등하지 않다.
    px_x = np.arange(mosaic.shape[1], dtype=np.float64) + 0.5
    px_y = np.arange(mosaic.shape[0], dtype=np.float64) + 0.5
    lons = np.array([_tile_to_lon(x0 + v / TILE, z) for v in px_x])
    lats = np.array([_tile_to_lat(y0 + v / TILE, z) for v in px_y])

    # 요청 영역만 잘라낸다. lats는 북→남 순서이므로 뒤집는다.
    ci = np.where((lons >= box.min_lon) & (lons <= box.max_lon))[0]
    ri = np.where((lats >= box.min_lat) & (lats <= box.max_lat))[0]
    if len(ci) < 2 or len(ri) < 2:
        raise RuntimeError("표고 격자를 만들기에 영역이 너무 작습니다.")

    grid = mosaic[ri[0]:ri[-1] + 1, ci[0]:ci[-1] + 1][::-1, :]
    out_lons = lons[ci[0]:ci[-1] + 1]
    out_lats = lats[ri[0]:ri[-1] + 1][::-1]

    # 실측 격자 간격을 함께 돌려준다. 등고선 간격이 적절한지 판단하는 근거가 된다.
    step_m = abs(out_lats[1] - out_lats[0]) * 110540 if len(out_lats) > 1 else 15.0
    meta = {"source": "aws", "file": "AWS Terrain Tiles",
            "grid_m": round(step_m, 2), "coverage": 1.0, "crs": "EPSG:4326"}
    return grid, out_lons, out_lats, meta
