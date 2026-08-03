"""추출 영역 계산과 경계 클리핑.

의존성을 줄이려고 shapely 대신 필요한 알고리즘만 직접 구현했다.
폴리곤은 Sutherland-Hodgman, 폴리라인은 Liang-Barsky를 쓴다.
"""
import math

EARTH_R = 6371008.8


class BBox:
    """경위도 사각 영역."""

    def __init__(self, min_lon, min_lat, max_lon, max_lat):
        self.min_lon = min(min_lon, max_lon)
        self.max_lon = max(min_lon, max_lon)
        self.min_lat = min(min_lat, max_lat)
        self.max_lat = max(min_lat, max_lat)

    @property
    def center(self):
        return ((self.min_lon + self.max_lon) / 2, (self.min_lat + self.max_lat) / 2)

    def width_m(self):
        lat = math.radians(self.center[1])
        return math.radians(self.max_lon - self.min_lon) * EARTH_R * math.cos(lat)

    def height_m(self):
        return math.radians(self.max_lat - self.min_lat) * EARTH_R

    def area_km2(self):
        return self.width_m() * self.height_m() / 1e6

    def expanded(self, meters):
        """가장자리에 걸치는 자료를 놓치지 않도록 여유를 둔다."""
        dlat = meters / EARTH_R * 180 / math.pi
        dlon = dlat / max(0.2, math.cos(math.radians(self.center[1])))
        return BBox(self.min_lon - dlon, self.min_lat - dlat,
                    self.max_lon + dlon, self.max_lat + dlat)

    def contains(self, lon, lat):
        return (self.min_lon <= lon <= self.max_lon
                and self.min_lat <= lat <= self.max_lat)

    def as_tuple(self):
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)

    def __repr__(self):
        return f"BBox({self.min_lon:.6f},{self.min_lat:.6f},{self.max_lon:.6f},{self.max_lat:.6f})"


def clip_polygon(ring, box: BBox):
    """Sutherland-Hodgman. 볼록한 클리핑 창(사각형)이므로 안전하다."""
    def inside(p, edge):
        if edge == 0:
            return p[0] >= box.min_lon
        if edge == 1:
            return p[0] <= box.max_lon
        if edge == 2:
            return p[1] >= box.min_lat
        return p[1] <= box.max_lat

    def intersect(a, b, edge):
        if edge in (0, 1):
            x = box.min_lon if edge == 0 else box.max_lon
            t = (x - a[0]) / (b[0] - a[0])
            return (x, a[1] + t * (b[1] - a[1]))
        y = box.min_lat if edge == 2 else box.max_lat
        t = (y - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), y)

    out = list(ring)
    for edge in range(4):
        if not out:
            return []
        buf, prev = [], out[-1]
        for cur in out:
            ci, pi = inside(cur, edge), inside(prev, edge)
            if ci:
                if not pi:
                    buf.append(intersect(prev, cur, edge))
                buf.append(cur)
            elif pi:
                buf.append(intersect(prev, cur, edge))
            prev = cur
        out = buf
    return out


def clip_polyline(pts, box: BBox):
    """구간별 Liang-Barsky. 잘린 조각들을 각각 반환한다."""
    pieces, cur = [], []
    for i in range(len(pts) - 1):
        seg = _clip_segment(pts[i], pts[i + 1], box)
        if seg is None:
            if len(cur) > 1:
                pieces.append(cur)
            cur = []
            continue
        a, b = seg
        if not cur:
            cur = [a, b]
        elif _close(cur[-1], a):
            cur.append(b)
        else:
            if len(cur) > 1:
                pieces.append(cur)
            cur = [a, b]
    if len(cur) > 1:
        pieces.append(cur)
    return pieces


def _close(a, b, eps=1e-12):
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def _clip_segment(a, b, box: BBox):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - box.min_lon), (dx, box.max_lon - a[0]),
                 (-dy, a[1] - box.min_lat), (dy, box.max_lat - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    if t0 > t1:
        return None
    return ((a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy))


def centroid(ring):
    """면적 가중 중심. 지번 문자를 놓을 위치로 쓴다."""
    a = cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-15:
        return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    a *= 0.5
    return (cx / (6 * a), cy / (6 * a))


def planar_area(ring):
    """투영 좌표(미터) 기준 신발끈 면적."""
    a = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2
