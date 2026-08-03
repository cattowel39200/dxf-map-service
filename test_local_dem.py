"""로컬 DEM 경로를 검증한다.

국토지리정보원 배포본과 같은 조건(5 m 격자 · EPSG:5186 중부원점 · ERDAS .img)의
파일을 만들어 넣고, 색인 → 선택 → 재투영 → 등고선 → DXF까지 이어지는지 확인한다.
실제 파일을 받기 전에 배선이 맞는지 보기 위한 것이다.
"""
import asyncio
import shutil
import sys

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from app import config
from app.contour import build_contours
from app.geom import BBox
from app.sources import dem, local_dem

FAIL = []
# 서울 남산 부근. 실제 DEM 파일과 겹치지 않게 시험용 이름을 쓴다.
CENTER_LON, CENTER_LAT = 126.9882, 37.5512
TEST_NAME = "_selftest_dem_5m.img"


def check(label, cond, detail=""):
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAIL.append(label)


def make_fake_ngii_dem(path, res=5.0, n=400):
    """중부원점 5 m 격자 .img. 표고는 소수점까지 있는 연속값으로 만든다."""
    tr = Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
    cx, cy = tr.transform(CENTER_LON, CENTER_LAT)
    x0, y1 = cx - n * res / 2, cy + n * res / 2

    gy, gx = np.mgrid[0:n, 0:n]
    dx = (gx - n / 2) * res
    dy = (n / 2 - gy) * res
    r2 = dx ** 2 + dy ** 2
    z = (120.0
         + 90.0 * np.exp(-r2 / (2 * 380.0 ** 2))       # 완만한 봉우리
         + 14.0 * np.sin(dx / 130.0)                    # 능선 굴곡
         + 9.0 * np.cos(dy / 95.0)
         + 0.7 * np.sin(dx / 23.0) * np.cos(dy / 19.0))  # 5 m급 미세 기복
    z = z.astype(np.float32)

    with rasterio.open(
        path, "w", driver="HFA", height=n, width=n, count=1,
        dtype="float32", crs="EPSG:5186",
        transform=from_origin(x0, y1, res, res), nodata=-9999.0,
    ) as ds:
        ds.write(z, 1)
    return z


async def main():
    config.DEM_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DEM_DIR / TEST_NAME
    print(f"[시험용 DEM 생성] {path.name}")
    z = make_fake_ngii_dem(path)
    print(f"  5 m 격자 400x400 (2 km 각) · 표고 {z.min():.1f}~{z.max():.1f} m"
          f" · {path.stat().st_size / 1024:.0f} KB\n")

    try:
        print("[색인]")
        files = local_dem.index(refresh=True)
        mine = [f for f in files if f.path.name == TEST_NAME]
        check("파일 인식", len(mine) == 1, f"총 {len(files)}개 색인")
        if not mine:
            return
        f = mine[0]
        check("좌표계 판독", "5186" in f.crs, f.crs)
        check("격자 간격 판독", abs(f.res_m - 5.0) < 0.2, f"{f.res_m} m")
        check("경위도 범위 변환",
              f.bounds[0] < CENTER_LON < f.bounds[2]
              and f.bounds[1] < CENTER_LAT < f.bounds[3],
              f"{f.bounds[0]:.4f},{f.bounds[1]:.4f} ~ {f.bounds[2]:.4f},{f.bounds[3]:.4f}")

        print("\n[선택 · 재투영]")
        box = BBox(CENTER_LON - 0.004, CENTER_LAT - 0.003,
                   CENTER_LON + 0.004, CENTER_LAT + 0.003)
        picked, cov = local_dem.pick(box)
        check("영역 덮음", picked is not None and cov > 0.99,
              f"커버리지 {cov:.3f}")

        grid, lons, lats, meta = await dem.load_dem(box)
        check("로컬 DEM 사용", meta["source"] == "local",
              f"{meta['source']} · {meta.get('file')}")
        check("격자 해상도 유지", abs(meta["grid_m"] - 5.0) < 0.2,
              f"{meta['grid_m']} m · 배열 {grid.shape}")

        # 재투영 후에도 표고가 원본 범위 안에 있어야 한다
        check("표고값 보존", z.min() - 3 < grid.min() and grid.max() < z.max() + 3,
              f"{grid.min():.1f}~{grid.max():.1f} m (원본 {z.min():.1f}~{z.max():.1f})")

        vals = np.unique(grid)
        frac = np.abs(vals - np.round(vals))
        check("연속 표고값 (양자화 없음)", frac.max() > 0.01,
              f"소수부 최대 {frac.max():.3f} — AWS는 0.000")

        print("\n[등고선]")
        for interval in (1.0, 5.0):
            cs = build_contours(grid, lons, lats, interval)
            check(f"{interval:g} m 간격", len(cs) > 3,
                  f"{len(cs)}개 선, 평균 {np.mean([len(c['pts']) for c in cs]):.0f}점")

        # AWS 대비 세밀도 비교
        cs_local = build_contours(grid, lons, lats, 5.0)
        pts_local = sum(len(c["pts"]) for c in cs_local)
        aws_grid, aws_lons, aws_lats, aws_meta = await dem._load_aws(box)
        cs_aws = build_contours(aws_grid, aws_lons, aws_lats, 5.0)
        pts_aws = sum(len(c["pts"]) for c in cs_aws)
        print(f"\n  같은 영역 5 m 등고선 정점 수")
        print(f"    로컬 5 m DEM : {pts_local:>6,}점 ({len(cs_local)}개 선)")
        print(f"    AWS {aws_meta['grid_m']:>4} m   : {pts_aws:>6,}점 ({len(cs_aws)}개 선)")

        print("\n[영역 밖 요청은 AWS로 넘어가는지]")
        far = BBox(128.60, 35.86, 128.61, 35.867)      # 대구
        _g, _lo, _la, m2 = await dem.load_dem(far)
        check("자동 대체", m2["source"] == "aws", f"{m2['source']}")

    finally:
        path.unlink(missing_ok=True)
        idx = config.DEM_DIR / ".index.json"
        idx.unlink(missing_ok=True)
        local_dem.index(refresh=True)
        print(f"\n  시험용 파일 정리 완료")

    print("\n" + "=" * 56)
    if FAIL:
        print(f"실패 {len(FAIL)}건: " + ", ".join(FAIL))
        return 1
    print("로컬 DEM 경로 정상")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
