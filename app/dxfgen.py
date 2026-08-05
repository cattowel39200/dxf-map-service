"""수집한 지오메트리를 DXF로 조립한다.

들어오는 좌표는 모두 EPSG:4326 경위도이고, 여기서 목표 좌표계로 변환한 뒤
레이어별로 배치한다. 좌표 변환을 이 단계에 몰아두어 소스 모듈은 좌표계를 모른다.
"""
import re
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
    ("A-REF", 4, 18, "기준점 · 방위표"),
]

TEXT_STYLE = "HANGUL"

# 종류마다 다른 색을 준다. 도면에 겹쳐 놓고 보아야 하므로 서로 잘 갈리는
# 것만 골랐다. 글자는 레이어 색을 따르므로 선과 저절로 같은 색이 된다.
PLAN_COLORS = [
    1, 3, 5, 2, 4, 6, 30, 130, 90, 50, 170, 210, 20, 110, 70, 190, 230, 150,
    40, 140, 60, 160, 80, 180, 100, 200, 120, 220, 10, 250, 34, 84, 134, 184,
    214, 24, 74, 124, 174, 224, 44, 94, 144, 194, 244, 14, 64, 114, 164, 204,
]

# 레이어 이름에 쓸 수 없는 글자. 제어문자까지 걸러 낸다.
_BAD_LAYER_CHARS = re.compile(r'[<>/\\":;?*|,=`]|[\x00-\x1f]')


def _plan_name(spec, props):
    """도형의 종류 이름. 레이어마다 이름이 담긴 칸이 달라 앞에서부터 찾는다."""
    for f in spec.get("fields") or ():
        v = (props.get(f) or "").strip()
        if v:
            return v
    return spec.get("label", "")


def _safe_layer(name: str) -> str:
    return re.sub(r"\s+", " ", _BAD_LAYER_CHARS.sub("", name)).strip()[:60]


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
        # 도시계획처럼 그때그때 만든 레이어. 정리할 때 구분하려고 둔다.
        self.made = set()
        # 도시계획 레이어에 돌아가며 줄 색의 차례
        self._cidx = 0

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

    def _ensure_layer(self, name, color=None, desc=""):
        """없으면 만든다. 도시계획은 종류가 수십 가지라 미리 다 만들지 않는다.

        색을 주지 않으면 목록에서 차례대로 뽑아 준다. 종류마다 색이 달라야
        도면에서 갈라 보인다.
        """
        if name not in self.doc.layers:
            if color is None:
                color = PLAN_COLORS[self._cidx % len(PLAN_COLORS)]
                self._cidx += 1
            lay = self.doc.layers.add(name, color=color)
            if desc:
                lay.description = desc[:255]
            if not self.r12:
                lay.dxf.lineweight = 18
        self.made.add(name)
        return name

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

    def add_planning(self, spec, shapes, sub_layers=True, draw_label=True):
        """도시계획·지역지구 도형을 넣는다.

        자료가 면(폴리곤)으로 오므로 테두리를 선으로 그린다. 도시계획선은
        곧 그 면의 경계선이다.

        sub_layers 를 켜면 종류마다 레이어를 나눈다. 도로를 예로 들면
        UP-도로-중로2류 처럼 갈라져 등급별로 끄고 켜기 쉽다.
        """
        base = spec["layer"]
        th = self._text_height()

        for s in shapes:
            kind = _plan_name(spec, s.get("props") or {})
            layer = base
            if sub_layers:
                safe = _safe_layer(kind)
                if safe:
                    layer = f"{base}-{safe}"
            self._ensure_layer(layer, None, f"{spec['label']} · {kind}")

            first = None
            shut = s.get("closed", True)
            for ring in s.get("rings") or []:
                pts = self._pts(ring)
                if len(pts) < 2:
                    continue
                if first is None:
                    first = pts
                self._polyline(pts, layer, closed=shut and len(pts) >= 3)

            # 무엇인지 도면에 적어 준다. 글자는 레이어 색을 따르므로
            # 그 선과 같은 색으로 나온다.
            if draw_label and kind and first and len(first) >= 3:
                self._text(kind, centroid(first), th * 0.9, layer)

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
        for name in [n for n, *_ in LAYERS] + sorted(self.made):
            if self.counts.get(name, 0) == 0 and name in self.doc.layers:
                try:
                    self.doc.layers.remove(name)
                except (ezdxf.DXFError, ValueError):
                    pass
        self.doc.saveas(path, encoding="utf-8")
        return path

    def stats(self):
        desc = {n: d for n, _c, _l, d in LAYERS}
        names = [n for n, *_ in LAYERS] + sorted(self.made)
        return [
            {"layer": n, "name": desc.get(n, n), "count": self.counts[n]}
            for n in names if self.counts.get(n, 0)
        ]
