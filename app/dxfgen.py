"""수집한 지오메트리를 DXF로 조립한다.

들어오는 좌표는 모두 EPSG:4326 경위도이고, 여기서 목표 좌표계로 변환한 뒤
레이어별로 배치한다. 좌표 변환을 이 단계에 몰아두어 소스 모듈은 좌표계를 모른다.
"""
from pathlib import Path

import ezdxf

from . import crs as crsmod
from .geom import BBox, centroid

DXF_VERSIONS = {
    "AC1032": "AutoCAD 2018",
    "AC1024": "AutoCAD 2010",
    "AC1015": "AutoCAD 2000",
    "AC1009": "AutoCAD R12",
}

# (레이어명, ACI 색, 선굵기 0.01mm 단위, 설명)
LAYERS = [
    ("D-PARCEL", 1, 25, "필지 경계"),
    ("D-PNU-TEXT", 7, 13, "지번 · 지목"),
    ("T-CONTOUR", 33, 9, "등고선 주곡선"),
    ("T-CONTOUR-INDEX", 32, 25, "등고선 계곡선"),
    ("T-BLDG", 8, 18, "건물"),
    ("T-ROAD", 2, 18, "도로 경계"),
    ("T-WATER", 5, 18, "하천 · 수계"),
    ("A-REF", 4, 18, "기준점 · 방위표"),
]

TEXT_STYLE = "HANGUL"


class DxfBuilder:
    def __init__(self, target_crs: str, options: dict, box: BBox):
        self.crs = str(target_crs)
        self.geographic = crsmod.SUPPORTED[self.crs].unit == "degree"
        self.opt = options
        self.box = box

        version = options.get("version", "AC1024")
        if version not in DXF_VERSIONS:
            version = "AC1024"
        self.version = version
        self.r12 = version == "AC1009"

        self.doc = ezdxf.new(version, setup=True)
        self.msp = self.doc.modelspace()
        self._setup_header()
        self._setup_layers()

        # 미터 → 도면 단위. 경위도 출력에서는 축척을 적용하지 않는다.
        self.scale = 1.0
        if not self.geographic and options.get("unit") == "mm":
            self.scale = 1000.0

        corner = crsmod.transform_point(box.min_lon, box.min_lat, self.crs)
        self.offset = (corner[0] * self.scale, corner[1] * self.scale) \
            if options.get("origin_shift") else (0.0, 0.0)

        self.counts = {}

    # ── 문서 준비 ───────────────────────────────
    def _setup_header(self):
        h = self.doc.header
        h["$MEASUREMENT"] = 1
        if self.r12:
            # R12 헤더에는 $INSUNITS / $LWDISPLAY 항목 자체가 없다.
            return
        h["$INSUNITS"] = 0 if self.geographic else (4 if self.opt.get("unit") == "mm" else 6)
        h["$LWDISPLAY"] = 1

    def _setup_layers(self):
        if TEXT_STYLE not in self.doc.styles:
            # DXF는 글꼴 파일명만 저장한다. 한글이 깨지지 않도록 맑은고딕을 지정.
            self.doc.styles.add(TEXT_STYLE, font="malgun.ttf")
        for name, color, lw, desc in LAYERS:
            lay = self.doc.layers.add(name, color=color)
            lay.description = desc
            if not self.r12:
                lay.dxf.lineweight = lw

    # ── 좌표 변환 ───────────────────────────────
    def _pts(self, ring):
        xy = crsmod.transform_ring(ring, self.crs)
        s, (ox, oy) = self.scale, self.offset
        return [(x * s - ox, y * s - oy) for x, y in xy]

    def _bump(self, layer, n=1):
        self.counts[layer] = self.counts.get(layer, 0) + n

    # ── 도형 추가 ───────────────────────────────
    def _polyline(self, pts, layer, closed=False, elevation=None):
        if len(pts) < 2:
            return
        attribs = {"layer": layer}
        if self.r12:
            pl = self.msp.add_polyline2d(pts, dxfattribs=attribs)
            pl.close(closed)
            if elevation is not None:
                pl.dxf.elevation = (0, 0, elevation)
        else:
            pl = self.msp.add_lwpolyline(pts, format="xy", dxfattribs=attribs)
            pl.closed = closed
            if elevation is not None:
                pl.dxf.elevation = elevation
        self._bump(layer)

    def _text(self, s, pos, height, layer, rotation=0.0):
        if not s:
            return
        t = self.msp.add_text(s, height=height, rotation=rotation, dxfattribs={
            "layer": layer, "style": TEXT_STYLE,
        })
        t.set_placement(pos, align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        self._bump(layer)

    # ── 레이어별 투입 ───────────────────────────
    def add_parcels(self, parcels, draw_boundary=True, draw_label=True):
        th = self._text_height()
        for p in parcels:
            for i, ring in enumerate(p["rings"]):
                pts = self._pts(ring)
                if len(pts) < 3:
                    continue
                if draw_boundary:
                    self._polyline(pts, "D-PARCEL", closed=True)
                if draw_label and i == 0:
                    cx, cy = centroid(pts)
                    label = p.get("jibun", "")
                    jimok = p.get("jimok", "")
                    if label:
                        self._text(label, (cx, cy + th * 0.7), th, "D-PNU-TEXT")
                    if jimok:
                        self._text(jimok, (cx, cy - th * 0.7), th * 0.85, "D-PNU-TEXT")

    def add_contours(self, contours, with_z=True):
        for c in contours:
            pts = self._pts(c["pts"])
            if len(pts) < 2:
                continue
            layer = "T-CONTOUR-INDEX" if c["index"] else "T-CONTOUR"
            z = c["elev"] * self.scale if (with_z and not self.geographic) else None
            if with_z and self.geographic:
                z = c["elev"]
            self._polyline(pts, layer, closed=False, elevation=z)

    def add_osm(self, features, want):
        mapping = {"building": "T-BLDG", "road": "T-ROAD", "water": "T-WATER"}
        for kind, layer in mapping.items():
            if kind not in want:
                continue
            for f in features.get(kind, []):
                pts = self._pts(f["pts"])
                self._polyline(pts, layer, closed=f["closed"])

    def add_reference_marks(self):
        """좌하단 기준점 십자와 방위표. 원점 이동을 켰을 때 특히 필요하다."""
        s = self.scale if not self.geographic else 1.0
        size = (40.0 * s) if not self.geographic else 0.0004
        base = crsmod.transform_point(self.box.min_lon, self.box.min_lat, self.crs)
        bx = base[0] * self.scale - self.offset[0]
        by = base[1] * self.scale - self.offset[1]

        self.msp.add_line((bx - size, by), (bx + size, by), dxfattribs={"layer": "A-REF"})
        self.msp.add_line((bx, by - size), (bx, by + size), dxfattribs={"layer": "A-REF"})
        self._bump("A-REF", 2)

        th = self._text_height()
        if self.geographic:
            label = f"기준점 EPSG:{self.crs}  {base[0]:.6f}, {base[1]:.6f}"
        else:
            label = f"기준점 EPSG:{self.crs}  X={base[0]:,.3f}  Y={base[1]:,.3f}"
        self._text(label, (bx + size * 4.2, by - size * 1.4), th, "A-REF")

        # 방위표 — 도곽 우상단.
        top = crsmod.transform_point(self.box.max_lon, self.box.max_lat, self.crs)
        nx = top[0] * self.scale - self.offset[0] - size * 3
        ny = top[1] * self.scale - self.offset[1] - size * 3
        self._polyline([(nx, ny), (nx - size * 0.6, ny - size * 2.4),
                        (nx, ny - size * 1.7), (nx + size * 0.6, ny - size * 2.4)],
                       "A-REF", closed=True)
        self._text("N", (nx, ny + th), th * 1.6, "A-REF")

    def _text_height(self):
        t = self.opt.get("text_height", "auto")
        if t == "auto":
            # 도곽 폭의 약 1/160. 1:1200 출력에서 읽히는 크기.
            meters = max(2.0, self.box.width_m() / 160.0)
        else:
            meters = float(t)
        if self.geographic:
            return meters / 111320.0
        return meters * self.scale

    # ── 저장 ───────────────────────────────────
    def save(self, path: Path):
        # 빈 레이어는 CAD에서 지저분하므로 정리한다.
        for name, *_ in LAYERS:
            if self.counts.get(name, 0) == 0 and name in self.doc.layers:
                try:
                    self.doc.layers.remove(name)
                except (ezdxf.DXFError, ValueError):
                    pass
        self.doc.saveas(path, encoding="utf-8")
        return path

    def stats(self):
        desc = {n: d for n, _c, _l, d in LAYERS}
        return [
            {"layer": n, "name": desc[n], "count": self.counts[n]}
            for n, *_ in LAYERS if self.counts.get(n, 0)
        ]
