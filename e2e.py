"""서버를 띄운 상태에서 실제 작업 한 건을 끝까지 돌린다.

    python e2e.py [포트]
"""
import sys
import time
from pathlib import Path

import ezdxf
import httpx

# 파이프로 넘길 때 콘솔 기본 코드페이지(cp949)에 막히지 않게 한다.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

PORT = sys.argv[1] if len(sys.argv) > 1 else "8011"
BASE = f"http://127.0.0.1:{PORT}"
# 서울 광진구 — 필지가 촘촘해 지적도 시험에 적합하다.
BBOX = [127.020, 37.550, 127.030, 37.557]


def main():
    cfg = httpx.get(f"{BASE}/api/config", timeout=20).json()
    print(f"한도 {cfg['max_area_km2']} km² · V-World 키 "
          f"{'있음' if cfg['has_vworld_key'] else '없음'}")

    layers = ["parcel", "pnu"]
    print(f"요청 레이어: {', '.join(layers)}")

    r = httpx.post(f"{BASE}/api/jobs", json={
        "bbox": BBOX,
        "crs": "5186",
        "layers": layers,
        "options": {"version": "AC1024", "unit": "m", "text_height": "auto",
                    "origin_shift": False, "reference_marks": True},
    }, timeout=30)
    if r.status_code != 202:
        print("작업 생성 실패:", r.status_code, r.text)
        return 1
    jid = r.json()["id"]
    print(f"작업 {jid} 시작")

    last = None
    t0 = time.time()
    while time.time() - t0 < 300:
        st = httpx.get(f"{BASE}/api/jobs/{jid}", timeout=20).json()
        line = f"{st['state']:8} {st['stage_label']:22} {st['progress'] * 100:5.1f}%"
        if line != last:
            print("  " + line)
            last = line
        if st["state"] in ("done", "error"):
            break
        time.sleep(0.7)

    if st["state"] != "done":
        print("실패:", st["error"])
        return 1

    print(f"\n완료 {st['elapsed']}초 · {st['filename']} · {st['size'] / 1024:.0f} KB")
    for l in st["layers"]:
        print(f"  {l['layer']:18} {l['name']:14} {l['count']:>7,}")

    out = Path("e2e_download.dxf")
    with httpx.stream("GET", f"{BASE}/api/jobs/{jid}/download", timeout=60) as resp:
        resp.raise_for_status()
        with out.open("wb") as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
    print(f"\n내려받음: {out} ({out.stat().st_size / 1024:.0f} KB)")

    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    ents = list(msp)
    xs = [p[0] for e in ents if e.dxftype() == "LWPOLYLINE" for p in e.get_points("xy")]
    ys = [p[1] for e in ents if e.dxftype() == "LWPOLYLINE" for p in e.get_points("xy")]

    for w in st.get("warnings", []):
        print(f"  [경고] {w}")

    print(f"\n검증 - 버전 {doc.dxfversion}, 객체 {len(ents)}개")
    print(f"  X 범위  {min(xs):,.1f} ~ {max(xs):,.1f}")
    print(f"  Y 범위  {min(ys):,.1f} ~ {max(ys):,.1f}")

    ok = True
    # 서울 중부원점 좌표대에 들어와야 한다
    if not (195_000 < min(xs) < 215_000 and 540_000 < min(ys) < 560_000):
        print("  [FAIL] 좌표가 EPSG:5186 서울 범위를 벗어났습니다")
        ok = False
    # 1 km 남짓 영역이므로 범위가 그 정도여야 한다
    if not (500 < max(xs) - min(xs) < 1500):
        print("  [FAIL] 도면 폭이 선택 영역과 맞지 않습니다")
        ok = False
    print("  [OK] 좌표계·범위 정상" if ok else "")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
