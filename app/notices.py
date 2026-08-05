"""공지사항.

관리페이지에서 등록하면 서비스 화면에 팝업으로 뜬다. 사용자가 '오늘 하루
보지 않음'을 누르면 그 공지는 하루 동안 다시 뜨지 않는다(브라우저 기준).
"""
import time

from . import db

KINDS = ("info", "warn", "event")


def _row(r) -> dict:
    d = dict(r)
    d["active"] = bool(d["active"])
    d["popup"] = bool(d["popup"])
    return d


def create(title: str, body: str = "", kind: str = "info",
           popup: bool = True, starts=None, ends=None) -> dict:
    if kind not in KINDS:
        kind = "info"
    now = time.time()
    with db.lock():
        c = db.connect()
        cur = c.execute(
            "INSERT INTO notices (title, body, kind, active, popup, starts, ends,"
            " created, updated) VALUES (?,?,?,1,?,?,?,?,?)",
            (title.strip(), body, kind, 1 if popup else 0, starts, ends, now, now))
        c.commit()
        nid = cur.lastrowid
    return get(nid)


def update(nid: int, **fields) -> dict | None:
    allowed = {"title", "body", "kind", "active", "popup", "starts", "ends"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("active", "popup"):
            v = 1 if v else 0
        if k == "kind" and v not in KINDS:
            v = "info"
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return get(nid)
    sets.append("updated=?")
    vals.append(time.time())
    vals.append(nid)
    with db.lock():
        c = db.connect()
        c.execute(f"UPDATE notices SET {','.join(sets)} WHERE id=?", vals)
        c.commit()
    return get(nid)


def delete(nid: int) -> bool:
    with db.lock():
        c = db.connect()
        cur = c.execute("DELETE FROM notices WHERE id=?", (nid,))
        c.commit()
        return cur.rowcount > 0


def get(nid: int) -> dict | None:
    with db.lock():
        r = db.connect().execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone()
    return _row(r) if r else None


def list_all() -> list[dict]:
    with db.lock():
        rows = db.connect().execute(
            "SELECT * FROM notices ORDER BY active DESC, created DESC").fetchall()
    return [_row(r) for r in rows]


def active(popup_only: bool = False) -> list[dict]:
    """지금 보여 줄 공지. 기간이 지정된 것은 기간 안에 있어야 한다."""
    now = time.time()
    sql = ("SELECT * FROM notices WHERE active=1"
           " AND (starts IS NULL OR starts <= ?)"
           " AND (ends   IS NULL OR ends   >= ?)")
    args = [now, now]
    if popup_only:
        sql += " AND popup=1"
    sql += " ORDER BY created DESC LIMIT 20"
    with db.lock():
        rows = db.connect().execute(sql, args).fetchall()
    return [_row(r) for r in rows]
