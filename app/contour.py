"""표고 격자에서 등고선을 뽑는다.

contourpy가 마칭스퀘어로 이어붙인 선을 돌려주므로 DXF에서 끊긴 세그먼트가 아니라
한 줄짜리 폴리라인이 된다. 주곡선/계곡선 구분은 간격의 5배로 판정한다.
"""
import numpy as np
from contourpy import contour_generator


def build_contours(grid, lons, lats, interval: float):
    """[{"elev": float, "index": bool, "pts": [(lon, lat), ...]}, ...]"""
    if grid.size == 0:
        return []

    valid = grid[np.isfinite(grid)]
    if valid.size == 0:
        return []
    lo = float(np.min(valid))
    hi = float(np.max(valid))
    if hi - lo < interval:
        return []

    # 표고 격자가 거칠 때 등고선이 계단처럼 각지는 것을 완화한다.
    smoothed = _smooth(grid)

    start = np.ceil(lo / interval) * interval
    levels = np.arange(start, hi + interval * 0.5, interval)
    if len(levels) > 400:
        raise RuntimeError(
            f"등고선 간격 {interval:g} m로는 선이 너무 많습니다({len(levels)}단계). "
            "간격을 넓혀 주세요."
        )

    gen = contour_generator(x=lons, y=lats, z=smoothed,
                            name="serial", line_type="SeparateCode")
    out = []
    index_step = interval * 5
    for lv in levels:
        lines, _codes = gen.lines(float(lv))
        is_index = abs(round(lv / index_step) * index_step - lv) < 1e-6
        for ln in lines:
            if len(ln) < 2:
                continue
            out.append({
                "elev": float(lv),
                "index": is_index,
                "pts": [(float(p[0]), float(p[1])) for p in ln],
            })
    return out


def _smooth(grid):
    """3x3 평균. 가장자리는 원본을 유지한다."""
    if grid.shape[0] < 3 or grid.shape[1] < 3:
        return grid
    out = grid.astype(np.float64, copy=True)
    acc = np.zeros_like(out[1:-1, 1:-1])
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            acc += out[1 + dj:out.shape[0] - 1 + dj, 1 + di:out.shape[1] - 1 + di]
    out[1:-1, 1:-1] = acc / 9.0
    return out


def sample_elevation(grid, lons, lats, lon, lat):
    """가장 가까운 격자점의 표고. 기준점 주기용."""
    i = int(np.clip(np.searchsorted(lons, lon), 0, len(lons) - 1))
    j = int(np.clip(np.searchsorted(lats, lat), 0, len(lats) - 1))
    return float(grid[j, i])
