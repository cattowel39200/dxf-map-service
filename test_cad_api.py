"""CADMAP.lsp가 부르는 경로를 그대로 흉내내 검증한다.

리습은 도면 좌표(TM)로 영역을 보내고, 받은 DXF의 좌표가 보낸 영역과 맞아야 한다.
AutoCAD 없이 확인할 수 있는 부분은 전부 여기서 확인한다.

    python test_cad_api.py [포트]
"""
import json
import re
import sys
import time
from pathlib import Path

import ezdxf
import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

PORT = sys.argv[1] if len(sys.argv) > 1 else "8000"
BASE = f"http://127.0.0.1:{PORT}"
FAIL = []

# AutoCAD에서 EPSG:5186 도면 위의 두 점을 찍었다고 가정
X0, Y0, X1, Y1 = 201800.0, 550000.0, 202250.0, 550380.0
CRS = "5186"


def check(label, cond, detail=""):
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        FAIL.append(label)


def lisp_jstr(js, key):
    """CADMAP.lsp의 cm:jstr 과 같은 방식으로 값을 뽑는다."""
    tag = f'"{key}":"'
    p = js.find(tag)
    if p < 0:
        return None
    p += len(tag)
    q = js.find('"', p)
    return js[p:q] if q > 0 else None


def lisp_jnum(js, key):
    tag = f'"{key}":'
    p = js.find(tag)
    if p < 0:
        return None
    m = re.match(r"[-+0-9.eE]+", js[p + len(tag):])
    return float(m.group()) if m else None


def main():
    print(f"AutoCAD 도면 좌표 (EPSG:{CRS})")
    print(f"  첫째 모서리  X={X0:,.1f}  Y={Y0:,.1f}")
    print(f"  반대 모서리  X={X1:,.1f}  Y={Y1:,.1f}")
    print(f"  영역 {X1 - X0:,.0f} x {Y1 - Y0:,.0f} m "
          f"= {(X1 - X0) * (Y1 - Y0) / 1e6:.4f} km2\n")

    print("[1] 도면 좌표로 작업 요청 (bbox_crs)")
    body = {
        "bbox": [X0, Y0, X1, Y1],
        "bbox_crs": CRS,
        "crs": CRS,
        "layers": ["parcel", "pnu", "contour"],
        "options": {"version": "AC1024", "unit": "m", "text_height": "auto",
                    "contour_interval": 5.0, "contour_z": True,
                    "origin_shift": False, "reference_marks": False},
    }
    r = httpx.post(f"{BASE}/api/jobs", json=body, timeout=30)
    check("HTTP 202 수락", r.status_code == 202,
          f"{r.status_code} {r.text[:120]}")
    if r.status_code != 202:
        return 1

    jid = lisp_jstr(r.text, "id")
    check("리습 방식 id 파싱", bool(jid) and len(jid) == 12, str(jid))

    print("\n[2] 진행 폴링")
    state, last, txt = "", "", ""
    t0 = time.time()
    while time.time() - t0 < 300:
        txt = httpx.get(f"{BASE}/api/jobs/{jid}", timeout=20).text
        state = lisp_jstr(txt, "state")
        stage = lisp_jstr(txt, "stage_label")
        prog = lisp_jnum(txt, "progress")
        if stage and stage != last:
            print(f"    {int((prog or 0) * 100):>3}%  {stage}")
            last = stage
        if state in ("done", "error"):
            break
        time.sleep(1)
    check("작업 완료", state == "done", state or "무응답")
    if state != "done":
        print("   ", lisp_jstr(txt, "error"))
        return 1

    # 리습이 "stage_label"을 "label"로 잘못 잡지 않는지 확인
    dem_label = lisp_jstr(txt, "label")
    stage_label = lisp_jstr(txt, "stage_label")
    check("label 파싱이 stage_label과 겹치지 않음",
          dem_label != stage_label,
          f"label={dem_label!r}")

    elapsed = lisp_jnum(txt, "elapsed")
    size = lisp_jnum(txt, "size")
    check("숫자 파싱", elapsed is not None and size is not None and size > 1000,
          f"{elapsed}초 {size / 1024:.0f} KB")

    print("\n[3] 다운로드 및 좌표 검증")
    out = Path("cad_test.dxf")
    with httpx.stream("GET", f"{BASE}/api/jobs/{jid}/download", timeout=120) as resp:
        resp.raise_for_status()
        with out.open("wb") as f:
            for c in resp.iter_bytes():
                f.write(c)
    check("파일 수신", out.stat().st_size > 10000, f"{out.stat().st_size / 1024:.0f} KB")

    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    pts = [p for e in msp if e.dxftype() == "LWPOLYLINE" for p in e.get_points("xy")]
    check("도형 존재", len(pts) > 100, f"정점 {len(pts):,}개")

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    print(f"    DXF X 범위  {min(xs):,.1f} ~ {max(xs):,.1f}   (요청 {X0:,.0f} ~ {X1:,.0f})")
    print(f"    DXF Y 범위  {min(ys):,.1f} ~ {max(ys):,.1f}   (요청 {Y0:,.0f} ~ {Y1:,.0f})")

    # 지켜야 할 조건은 두 가지다.
    #  (1) 요청한 영역을 빠짐없이 덮을 것 — 이게 어긋나면 도면에 구멍이 난다
    #  (2) 바깥으로 나가더라도 설명 가능한 범위일 것
    #      경계에 걸친 필지는 통째로 살리고, 등고선은 가장자리가 잘리지 않게
    #      120 m 여유를 두고 만들기 때문에 어느 정도는 넘어가는 게 정상이다.
    check("요청 영역을 모두 덮음",
          min(xs) <= X0 and max(xs) >= X1 and min(ys) <= Y0 and max(ys) >= Y1,
          f"좌 {X0 - min(xs):+,.0f}  우 {max(xs) - X1:+,.0f}  "
          f"하 {Y0 - min(ys):+,.0f}  상 {max(ys) - Y1:+,.0f} m")

    over = max(X0 - min(xs), max(xs) - X1, Y0 - min(ys), max(ys) - Y1)
    check("바깥 여유가 설명 가능한 범위", over < 400, f"최대 {over:,.0f} m")

    layers = {e.dxf.layer for e in msp}
    check("레이어 구성", {"D-PARCEL", "D-PNU-TEXT"} <= layers,
          ", ".join(sorted(layers)))

    print("\n[4] 잘못된 입력 처리")
    bad = httpx.post(f"{BASE}/api/jobs", json={**body, "bbox_crs": "9999"}, timeout=20)
    check("없는 좌표계 거부", bad.status_code == 400,
          json.loads(bad.text).get("detail", "")[:60])

    big = httpx.post(f"{BASE}/api/jobs", json={
        **body, "bbox": [X0, Y0, X0 + 3000, Y0 + 3000]}, timeout=20)
    check("한도 초과 거부", big.status_code == 400,
          json.loads(big.text).get("detail", "")[:70])

    out.unlink(missing_ok=True)
    print("\n" + "=" * 58)
    if FAIL:
        print(f"실패 {len(FAIL)}건: " + ", ".join(FAIL))
        return 1
    print("CAD 연동 경로 정상")
    return 0


if __name__ == "__main__":
    sys.exit(main())
