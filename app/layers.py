"""추출할 수 있는 레이어 목록.

V-World 355개 레이어를 모두 훑어 실제로 벡터가 내려오는 것만 골라 담았다.
각 항목은 화면(웹·리습)의 선택 목록이 되고, 그대로 DXF 레이어 이름이 된다.

name 필드가 여럿인 까닭: V-World 레이어마다 이름이 담긴 칸이 제각각이다.
uname 인 것도 있고 dgm_nm·lcl_nam 인 것도 있어, 앞에서부터 찾아 쓴다.
"""
from __future__ import annotations

# 지적도. 이것만 따로 다뤄 온 기존 코드가 있어 키를 그대로 둔다.
CADASTRAL = ("parcel", "pnu")

# (키, 화면 이름, 묶음, V-World 레이어, 이름칸, DXF 레이어, 색)
#
# 색은 AutoCAD 색 번호(ACI). 묶음별로 계열을 맞춰 도면에서 구분되게 했다.
SPECS: list[tuple] = [
    # ── 도시계획시설 ──────────────────────────────────────────
    ("up_road",   "도시계획 도로",       "도시계획시설", "LT_C_UPISUQ151",
     ("dgm_nm", "lcl_nam"),        "UP-도로",        1),
    ("up_traf",   "교통시설",            "도시계획시설", "LT_C_UPISUQ152",
     ("dgm_nm", "sclas_cl"),       "UP-교통시설",     30),
    ("up_space",  "공원 · 녹지",         "도시계획시설", "LT_C_UPISUQ153",
     ("dgm_nm", "exc_nam"),        "UP-공원녹지",     3),
    ("up_supply", "유통 · 공급시설",      "도시계획시설", "LT_C_UPISUQ154",
     ("dgm_nm", "sclas_cl"),       "UP-유통공급",     6),
    ("up_pub",    "공공 · 문화체육시설",   "도시계획시설", "LT_C_UPISUQ155",
     ("dgm_nm", "sclas_cl"),       "UP-공공문화체육",  5),
    ("up_prev",   "방재시설",            "도시계획시설", "LT_C_UPISUQ156",
     ("dgm_nm", "sclas_cl"),       "UP-방재시설",     4),
    ("up_san",    "보건위생시설",         "도시계획시설", "LT_C_UPISUQ157",
     ("dgm_nm", "sclas_cl"),       "UP-보건위생",     140),
    ("up_env",    "환경기초시설",         "도시계획시설", "LT_C_UPISUQ158",
     ("dgm_nm", "sclas_cl"),       "UP-환경기초",     94),
    ("up_etc",    "기타기반시설",         "도시계획시설", "LT_C_UPISUQ159",
     ("dgm_nm", "sclas_cl"),       "UP-기타기반",     8),
    ("up_dist",   "지구단위계획구역",      "도시계획시설", "LT_C_UPISUQ161",
     ("dgm_nm", "lcl_nam"),        "UP-지구단위",     202),

    # ── 용도지역 ──────────────────────────────────────────────
    ("uq_urban",  "도시지역",            "용도지역", "LT_C_UQ111",
     ("uname",),                   "UQ-도시지역",     2),
    ("uq_manage", "관리지역",            "용도지역", "LT_C_UQ112",
     ("uname",),                   "UQ-관리지역",     42),
    ("uq_agri",   "농림지역",            "용도지역", "LT_C_UQ113",
     ("uname",),                   "UQ-농림지역",     82),
    ("uq_nature", "자연환경보전지역",      "용도지역", "LT_C_UQ114",
     ("uname",),                   "UQ-자연환경보전",  102),

    # ── 용도지구 ──────────────────────────────────────────────
    ("ug_view",   "경관지구",            "용도지구", "LT_C_UQ121",
     ("uname",),                   "UG-경관지구",     130),
    ("ug_height", "고도지구",            "용도지구", "LT_C_UQ123",
     ("uname",),                   "UG-고도지구",     131),
    ("ug_fire",   "방화지구",            "용도지구", "LT_C_UQ124",
     ("uname",),                   "UG-방화지구",     132),
    ("ug_disas",  "방재지구",            "용도지구", "LT_C_UQ125",
     ("uname",),                   "UG-방재지구",     133),
    ("ug_prot",   "보호지구",            "용도지구", "LT_C_UQ126",
     ("uname",),                   "UG-보호지구",     134),
    ("ug_vill",   "취락지구",            "용도지구", "LT_C_UQ128",
     ("uname",),                   "UG-취락지구",     135),
    ("ug_dev",    "개발진흥지구",         "용도지구", "LT_C_UQ129",
     ("uname",),                   "UG-개발진흥지구",  136),
    ("ug_limit",  "특정용도제한지구",      "용도지구", "LT_C_UQ130",
     ("uname",),                   "UG-특정용도제한",  137),

    # ── 용도구역 ──────────────────────────────────────────────
    ("uz_green",  "개발제한구역",         "용도구역", "LT_C_UD801",
     ("uname",),                   "UZ-개발제한구역",  90),
    ("uz_park",   "도시자연공원구역",      "용도구역", "LT_C_UQ162",
     ("uname",),                   "UZ-도시자연공원",  92),

    # ── 개별법령에 따른 지역지구 ───────────────────────────────
    # 절대·상대보호구역이 한 레이어에 함께 들어 있다.
    ("etc_school", "교육환경보호구역",     "개별법령", "LT_C_UO101",
     ("uname",),                   "ETC-교육환경보호",  200),
    ("etc_herit",  "국가유산 지정 · 보호구역", "개별법령", "LT_C_UO301",
     ("uname",),                   "ETC-국가유산",     34),
    ("etc_forest", "산림보호구역",         "개별법령", "LT_C_UF151",
     ("uname",),                   "ETC-산림보호",     84),
    ("etc_hazard", "재해위험지구",         "개별법령", "LT_C_UP201",
     ("uname",),                   "ETC-재해위험",     10),
    ("etc_stock",  "가축사육제한구역",      "개별법령", "LT_C_UM000",
     ("uname",),                   "ETC-가축사육제한",  250),
    ("etc_agri",   "농업진흥 · 보호구역",   "개별법령", "LT_C_AGRIXUE101",
     ("uname",),                   "ETC-농업진흥",     52),
    ("etc_poor",   "영농여건불리농지",      "개별법령", "LT_C_AGRIXUE102",
     ("uname",),                   "ETC-영농여건불리",  62),
    ("etc_house",  "주거환경개선지구",      "개별법령", "LT_C_UD601",
     ("uname",),                   "ETC-주거환경개선",  210),
    ("etc_temple", "전통사찰보존구역",      "개별법령", "LT_C_UO501",
     ("uname",),                   "ETC-전통사찰",     44),
    ("etc_water",  "상수원보호구역",       "개별법령", "LT_C_UM710",
     ("uname",),                   "ETC-상수원보호",   150),
    ("etc_wild",   "야생동식물보호구역",    "개별법령", "LT_C_UM221",
     ("uname",),                   "ETC-야생동식물",   112),
    ("etc_wet",    "습지보호지역",         "개별법령", "LT_C_UM901",
     ("uname",),                   "ETC-습지보호",     122),
    ("etc_ridge",  "백두대간보호지역",      "개별법령", "LT_C_UF901",
     ("uname",),                   "ETC-백두대간",     104),
    ("etc_slope",  "급경사재해예방지역",    "개별법령", "LT_C_UP401",
     ("uname",),                   "ETC-급경사재해",   12),
    ("etc_air",    "대기환경규제지역",      "개별법령", "LT_C_UM301",
     ("uname",),                   "ETC-대기환경규제",  152),
    ("etc_permit", "개발행위허가제한지역",   "개별법령", "LT_C_UPISUQ171",
     ("uname", "dgm_nm"),          "ETC-개발행위제한",  20),

    # ── 하천 · 도로 ───────────────────────────────────────────
    # 하천망은 이름만 그럴 뿐 실제로는 하천 구역 면이다.
    # 국가하천 · 지방1급 · 지방2급으로 갈려 들어온다.
    ("riv_zone",  "하천구역",            "하천 · 도로", "LT_C_WKMSTRM",
     ("cat_nam",),                 "RV-하천구역",     150),
    ("riv_basin", "표준유역",            "하천 · 도로", "LT_C_WKMSBSN",
     ("sbsnnm",),                  "RV-표준유역",     151),
    # 도로법상 도로구역(고시 면)은 V-World 에 없다. 대신 등급이 붙은
    # 도로 중심선을 넣는다. 고속국도부터 시·군도까지 위계가 그대로 나온다.
    ("rd_link",   "도로 중심선 (등급별)",  "하천 · 도로", "LT_L_MOCTLINK",
     ("rd_rank_h",),               "RD-도로등급",     7),
    ("rd_addr",   "도로명주소 도로",       "하천 · 도로", "LT_L_SPRD",
     (),                           "RD-도로명주소",    8),
]

# 종류마다 레이어를 나누면 도리어 지저분해지는 것. 하나로 묶는다.
# 도로명주소 도로는 1 km2 안에 이름이 백 가지가 넘는다.
NO_SPLIT = {"rd_addr", "riv_basin"}

# 자동 조사분이 이름을 담는 칸은 레이어마다 제각각이라, 흔한 것을
# 앞에서부터 찾아 쓴다. 없으면 제목이 그대로 쓰인다.
GENERIC_FIELDS = ("uname", "dgm_nm", "name", "nm", "kname", "fac_nam",
                  "riv_nm", "sbsnnm", "exc_nam", "lcl_nam", "grade")

# 화면에 그대로 쓰는 사전
CATALOG = {
    s[0]: {"key": s[0], "label": s[1], "group": s[2], "source": s[3],
           "fields": s[4], "layer": s[5], "color": s[6], "api": "data"}
    for s in SPECS
}

# V-World 전 레이어를 조사해 벡터가 나온 것들 (Data API 82 + WFS 50)
from .layers_auto import AUTO as _AUTO      # noqa: E402

def _safe(s):
    import re as _re
    return _re.sub(r"[^\w가-힣()]+", "", s)[:24]

for _k, _label, _grp, _src, _api in _AUTO:
    if _k in CATALOG:
        continue
    CATALOG[_k] = {"key": _k, "label": _label, "group": _grp, "source": _src,
                   "fields": GENERIC_FIELDS, "layer": "TM-" + _safe(_label),
                   "color": 7, "api": _api}

KEYS = tuple(CATALOG)
GROUPS = ("도시계획시설", "용도지역", "용도지구", "용도구역",
          "개별법령", "하천 · 도로",
          "항공 · 군사", "교육 · 학군", "환경 · 지질", "해양 · 수자원",
          "산업 · 개발", "생활 · 관광", "공공 · 행정", "기타 주제도")

# V-World 에 아예 없어 넣지 못한 것. 화면에 그대로 밝혀 둔다.
UNAVAILABLE = [
    ("도로구역(고시 면)", "도로법 — 등급별 중심선으로 대신함"),
    ("접도구역", "도로법"),
    ("철도보호지구", "철도안전법"), ("택지개발예정지구", "택지개발촉진법"),
    ("정비구역", "도시정비법"), ("농업생산기반 정비사업지구", "농어촌정비법"),
    ("사방지", "사방사업법"), ("임업용산지", "산지관리법"),
    ("공익용산지", "산지관리법"), ("준보전산지", "산지관리법"),
    ("소하천구역", "소하천정비법"), ("소하천예정지", "소하천정비법"),
    ("공장설립제한지역", "수도법"),
    ("공장설립승인지역", "수도법"), ("배출시설설치제한지역", "물환경보전법"),
]


# 종류마다 다른 색을 준다. 도면에 겹쳐 놓고 보아야 하므로 서로 잘 갈리는
# 것만 골랐다. 글자는 레이어 색을 따르므로 선과 저절로 같은 색이 된다.
PLAN_COLORS = [
    1, 3, 5, 2, 4, 6, 30, 130, 90, 50, 170, 210, 20, 110, 70, 190, 230, 150,
    40, 140, 60, 160, 80, 180, 100, 200, 120, 220, 10, 250, 34, 84, 134, 184,
    214, 24, 74, 124, 174, 224, 44, 94, 144, 194, 244, 14, 64, 114, 164, 204,
]


def color_map(pairs) -> dict:
    """(자료키, 종류이름) 마다 서로 다른 색을 준다.

    늘 같은 차례로 주므로, 지도에 미리 보이는 색과 도면에 들어가는 색이
    같아진다. 색을 그때그때 만들면 화면과 도면이 어긋나 헷갈린다.
    """
    def rank(p):
        return (KEYS.index(p[0]) if p[0] in KEYS else 999, p[1])
    order = sorted({(a, b) for a, b in pairs}, key=rank)
    return {p: PLAN_COLORS[i % len(PLAN_COLORS)] for i, p in enumerate(order)}


def catalog() -> list[dict]:
    """묶음 차례대로 늘어놓는다. 화면 목록에 그대로 쓴다."""
    out = []
    for g in GROUPS:
        for c in CATALOG.values():
            if c["group"] == g:
                out.append(dict(c))
    return out


def pick(keys) -> list[dict]:
    """고른 키만 목록 차례대로 돌려준다. 모르는 키는 버린다."""
    want = {k for k in (keys or []) if k in CATALOG}
    return [c for c in catalog() if c["key"] in want]


def name_of(spec: dict, props: dict) -> str:
    """이 도형의 종류 이름. 칸이 레이어마다 달라 앞에서부터 찾는다."""
    for f in spec["fields"]:
        v = (props.get(f) or "").strip()
        if v:
            return v
    return spec["label"]
