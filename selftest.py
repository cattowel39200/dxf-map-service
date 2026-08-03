"""동작 확인용 자체 점검. 인증키 없이 돌아가는 부분만 검사한다.

    python selftest.py          # 오프라인 검사만
    python selftest.py --live   # 표고·OSM 실제 조회까지
"""
import asyncio
import sys
import tempfile
from pathlib import Path

import ezdxf

from app import crs
from app.contour import build_contours
from app.dxfgen import DxfBuilder
from app.geom import BBox, centroid, clip_polygon, clip_polyline

FAIL = []


def check(label, cond, detail=""):
    mark = "OK  " if cond else "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAIL.append(label)


def test_crs():
    print("\n[좌표계 변환]")
    # 국토지리정보원 공표 성과와 대조 (서울시청 / 부산시청)
    x, y = crs.transform_point(126.9780, 37.5665, "5186")
    check("EPSG:5186 서울시청", abs(x - 198056) < 60 and abs(y - 551885) < 60,
          f"X={x:,.1f} Y={y:,.1f}")

    x, y = crs.transform_point(126.9780, 37.5665, "5179")
    check("EPSG:5179 UTM-K 서울시청", abs(x - 953901) < 60 and abs(y - 1952032) < 60,
          f"X={x:,.1f} Y={y:,.1f}")

    x, y = crs.transform_point(129.0756, 35.1796, "5187")
    check("EPSG:5187 동부원점 부산시청", abs(x - 206886) < 60 and abs(y - 287023) < 60,
          f"X={x:,.1f} Y={y:,.1f}")

    # 구지적은 세계측지계와 수백 m 어긋나는 것이 정상이다.
    x74, y74 = crs.transform_point(126.9780, 37.5665, "5174")
    check("EPSG:5174 구지적 데이텀 차이", 100 < abs((y74 + 100000) - 551885) < 600,
          f"Y차 {abs((y74 + 100000) - 551885):,.1f} m")

    lon, lat = crs.transform_point(126.9780, 37.5665, "4326")
    check("EPSG:4326 항등", abs(lon - 126.9780) < 1e-9, f"{lon}, {lat}")

    check("좌표계 목록", len(crs.catalog()) == 3 and len(crs.SUPPORTED) == 8)


def test_geom():
    print("\n[영역 계산 · 클리핑]")
    box = BBox(126.94, 37.18, 126.95, 37.187)
    check("면적 계산", 0.5 < box.area_km2() < 0.8, f"{box.area_km2():.4f} km²")
    check("폭/높이", 800 < box.width_m() < 950 and 700 < box.height_m() < 820,
          f"{box.width_m():.0f} x {box.height_m():.0f} m")

    ring = [(126.935, 37.175), (126.955, 37.175), (126.955, 37.19), (126.935, 37.19)]
    out = clip_polygon(ring, box)
    check("폴리곤 클리핑", len(out) == 4
          and all(box.min_lon - 1e-9 <= p[0] <= box.max_lon + 1e-9 for p in out),
          f"{len(out)}점")

    line = [(126.930, 37.182), (126.960, 37.182)]
    pieces = clip_polyline(line, box)
    check("폴리라인 클리핑", len(pieces) == 1 and len(pieces[0]) == 2,
          f"{len(pieces)}조각")

    outside = clip_polyline([(126.90, 37.10), (126.91, 37.11)], box)
    check("영역 밖 폴리라인 제거", outside == [])

    c = centroid([(0, 0), (10, 0), (10, 10), (0, 10)])
    check("중심점", abs(c[0] - 5) < 1e-9 and abs(c[1] - 5) < 1e-9, str(c))


def _fake_parcels(box):
    """격자로 나눈 가짜 필지."""
    out = []
    n = 4
    dx = (box.max_lon - box.min_lon) / n
    dy = (box.max_lat - box.min_lat) / n
    for i in range(n):
        for j in range(n):
            x0, y0 = box.min_lon + dx * i, box.min_lat + dy * j
            out.append({
                "pnu": f"41590250{i}{j}",
                "jibun": f"{100 + i * 10 + j}-{j + 1}",
                "jimok": "전" if (i + j) % 2 else "대",
                "rings": [[(x0, y0), (x0 + dx, y0), (x0 + dx, y0 + dy), (x0, y0 + dy)]],
            })
    return out


def _fake_contours(box):
    import numpy as np
    lons = np.linspace(box.min_lon, box.max_lon, 60)
    lats = np.linspace(box.min_lat, box.max_lat, 60)
    gx, gy = np.meshgrid(np.linspace(-2, 2, 60), np.linspace(-2, 2, 60))
    grid = 50 + 60 * np.exp(-(gx ** 2 + gy ** 2)) + 8 * gx
    return build_contours(grid, lons, lats, 5.0)


def test_dxf():
    print("\n[DXF 생성]")
    box = BBox(126.94, 37.18, 126.95, 37.187)
    parcels = _fake_parcels(box)
    contours = _fake_contours(box)
    check("등고선 생성", len(contours) > 5, f"{len(contours)}개 선")
    check("계곡선 구분", any(c["index"] for c in contours)
          and any(not c["index"] for c in contours))

    osm = {
        "building": [{"pts": [(126.942, 37.181), (126.9425, 37.181),
                              (126.9425, 37.1815), (126.942, 37.1815)],
                      "closed": True, "name": ""}],
        "road": [{"pts": [(126.940, 37.183), (126.950, 37.1835)],
                  "closed": False, "name": "지방도"}],
        "water": [],
    }

    tmp = Path(tempfile.mkdtemp())
    for version in ("AC1024", "AC1009", "AC1032"):
        for code in ("5186", "5174", "4326"):
            opts = {"version": version, "unit": "m", "text_height": "auto",
                    "contour_z": True, "origin_shift": False,
                    "reference_marks": True}
            b = DxfBuilder(code, opts, box)
            b.add_parcels(parcels)
            b.add_contours(contours)
            b.add_osm(osm, {"building", "road"})
            b.add_reference_marks()
            path = b.save(tmp / f"t_{version}_{code}.dxf")

            doc = ezdxf.readfile(path)
            msp = doc.modelspace()
            layers = {e.dxf.layer for e in msp}
            texts = [e for e in msp if e.dxftype() == "TEXT"]
            check(f"{version} / EPSG:{code}",
                  "D-PARCEL" in layers and "D-PNU-TEXT" in layers
                  and "T-CONTOUR" in layers and "T-BLDG" in layers
                  and len(texts) > 0 and path.stat().st_size > 5000,
                  f"{len(list(msp))}객체 {path.stat().st_size // 1024}KB")

    # 한글 지번이 왕복해도 보존되는지
    doc = ezdxf.readfile(tmp / "t_AC1024_5186.dxf")
    jimoks = {e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT"}
    check("한글 지목 보존", "전" in jimoks and "대" in jimoks,
          f"{sorted(j for j in jimoks if len(j) == 1)}")

    # 원점 이동을 켜면 좌하단이 0 근처로 와야 한다
    opts = {"version": "AC1024", "unit": "m", "text_height": "auto",
            "contour_z": True, "origin_shift": True, "reference_marks": False}
    b = DxfBuilder("5186", opts, box)
    b.add_parcels(parcels)
    p = b.save(tmp / "shift.dxf")
    doc = ezdxf.readfile(p)
    xs = [pt[0] for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"
          for pt in e.get_points("xy")]
    check("원점 이동", 0 <= min(xs) < 5, f"min X = {min(xs):.3f}")

    # mm 단위는 좌표가 1000배
    opts = {"version": "AC1024", "unit": "mm", "text_height": "auto",
            "contour_z": True, "origin_shift": True, "reference_marks": False}
    b = DxfBuilder("5186", opts, box)
    b.add_parcels(parcels)
    p = b.save(tmp / "mm.dxf")
    doc = ezdxf.readfile(p)
    xs_mm = [pt[0] for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"
             for pt in e.get_points("xy")]
    check("mm 단위 축척", 900 < max(xs_mm) / max(xs) < 1100,
          f"{max(xs_mm):.0f}mm vs {max(xs):.0f}m")

    print(f"  산출물: {tmp}")


async def test_live():
    print("\n[실제 조회 — 네트워크]")
    from app.sources import dem, osm as osmsrc

    box = BBox(127.02, 37.55, 127.03, 37.557)   # 서울 아차산 일대
    try:
        grid, lons, lats, meta = await dem.load_dem(box)
        check("표고 자료 조회", grid.size > 1000 and float(grid.max()) > 10,
              f"{meta['source']} · 격자 {meta['grid_m']} m · {grid.shape} "
              f"표고 {grid.min():.0f}~{grid.max():.0f} m")
        cs = build_contours(grid, lons, lats, 5.0)
        check("실제 등고선", len(cs) > 3, f"{len(cs)}개 선")
    except Exception as exc:  # noqa: BLE001
        check("AWS 표고 타일", False, str(exc))

    try:
        feats = await osmsrc.fetch_features(box)
        check("OSM 지형지물", sum(len(v) for v in feats.values()) > 0,
              ", ".join(f"{k} {len(v)}" for k, v in feats.items()))
    except Exception as exc:  # noqa: BLE001
        check("OSM 지형지물", False, str(exc))


def test_app_imports():
    print("\n[FastAPI 앱]")
    from app.main import app
    routes = {r.path for r in app.routes}
    check("라우트 등록", {"/api/config", "/api/jobs", "/api/project",
                      "/api/parcels"} <= routes,
          f"{len(routes)}개")


if __name__ == "__main__":
    test_crs()
    test_geom()
    test_dxf()
    test_app_imports()
    if "--live" in sys.argv:
        asyncio.run(test_live())

    print("\n" + "=" * 52)
    if FAIL:
        print(f"실패 {len(FAIL)}건: " + ", ".join(FAIL))
        sys.exit(1)
    print("모든 검사 통과")
