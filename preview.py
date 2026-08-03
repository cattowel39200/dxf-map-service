"""생성된 DXF를 SVG로 그려 눈으로 확인한다. 서비스 기능은 아니고 점검용 도구다.

    python preview.py e2e_download.dxf preview.svg
"""
import sys
from pathlib import Path

import ezdxf

COLOR = {
    "D-PARCEL": ("#C0453C", 0.9),
    "D-PNU-TEXT": ("#7A4B2E", 0.5),
    "T-CONTOUR": ("#A5713F", 0.45),
    "T-CONTOUR-INDEX": ("#8A5628", 1.0),
    "T-BLDG": ("#5F7480", 0.7),
    "T-ROAD": ("#C08A22", 1.1),
    "T-WATER": ("#2E7FA8", 1.3),
    "A-REF": ("#0F5F73", 0.8),
}


def main(src, dst):
    doc = ezdxf.readfile(src)
    msp = doc.modelspace()

    lines = []          # (layer, [(x, y), ...])
    labels = []         # (layer, x, y, text, height)
    for e in msp:
        t = e.dxftype()
        if t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            if e.closed and pts:
                pts.append(pts[0])
            lines.append((e.dxf.layer, pts))
        elif t == "POLYLINE":
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            if e.is_closed and pts:
                pts.append(pts[0])
            lines.append((e.dxf.layer, pts))
        elif t == "LINE":
            lines.append((e.dxf.layer, [(e.dxf.start.x, e.dxf.start.y),
                                        (e.dxf.end.x, e.dxf.end.y)]))
        elif t == "TEXT":
            p = e.dxf.insert
            labels.append((e.dxf.layer, p.x, p.y, e.dxf.text, e.dxf.height))

    allpts = [p for _l, pts in lines for p in pts] + [(x, y) for _l, x, y, *_ in labels]
    if not allpts:
        print("그릴 도형이 없습니다.")
        return 1
    xs = [p[0] for p in allpts]
    ys = [p[1] for p in allpts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = max(maxx - minx, maxy - miny) * 0.03
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    w, h = maxx - minx, maxy - miny

    W = 1100
    H = round(W * h / w)
    sx = W / w

    def X(v):
        return (v - minx) * sx

    def Y(v):
        return (maxy - v) * sx

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}"><rect width="{W}" height="{H}" fill="#FBFAF7"/>']

    order = ["T-CONTOUR", "T-CONTOUR-INDEX", "T-WATER", "T-ROAD",
             "T-BLDG", "D-PARCEL", "A-REF", "D-PNU-TEXT"]
    for layer in order:
        col, lw = COLOR.get(layer, ("#666", 0.6))
        seg = [pts for lay, pts in lines if lay == layer]
        if seg:
            d = " ".join("M" + " L".join(f"{X(p[0]):.1f},{Y(p[1]):.1f}" for p in pts)
                         for pts in seg if len(pts) > 1)
            fill = "#5F748022" if layer == "T-BLDG" else "none"
            out.append(f'<path d="{d}" fill="{fill}" stroke="{col}" '
                       f'stroke-width="{lw}" stroke-linejoin="round"/>')

    for layer, x, y, text, height in labels:
        col, _ = COLOR.get(layer, ("#666", 0.6))
        fs = max(5.0, height * sx)
        esc = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        out.append(f'<text x="{X(x):.1f}" y="{Y(y) + fs * 0.35:.1f}" fill="{col}" '
                   f'font-size="{fs:.1f}" text-anchor="middle" '
                   f'font-family="Malgun Gothic, sans-serif">{esc}</text>')

    out.append("</svg>")
    Path(dst).write_text("".join(out), encoding="utf-8")

    counts = {}
    for lay, _ in lines:
        counts[lay] = counts.get(lay, 0) + 1
    print(f"{dst} 저장 · {W}x{H}px")
    print(f"도면 범위 {w:,.0f} x {h:,.0f} (도면 단위)")
    for k, v in sorted(counts.items()):
        print(f"  {k:18} {v:>6}")
    if labels:
        print(f"  {'TEXT':18} {len(labels):>6}")
    return 0


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "e2e_download.dxf"
    dst = sys.argv[2] if len(sys.argv) > 2 else "preview.svg"
    sys.exit(main(src, dst))
