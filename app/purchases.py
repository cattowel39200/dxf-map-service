"""정품 구매 신청.

리습의 '정품신청' 창에서 보낸 신청을 받아 두고, 관리자가 입금을 확인해
정품으로 바꿔 줄 때까지 '신청중'으로 남긴다. 세금계산서를 원하는 사람은
사업자 정보를 같이 보내고, 관리자는 발급을 마치면 표시해 둔다.

입금자명은 PC 번호를 쓰게 한다. 이름으로 넣으면 누가 보낸 것인지
가려내기 어렵지만, PC 번호는 발급키에 묶여 있어 바로 이어진다.
"""
from __future__ import annotations

import time

from . import config, db, settings

FIELDS = ("req_name", "contact", "biz_no", "biz_name", "biz_addr",
          "biz_type")


def _row(key: str) -> dict | None:
    with db.lock():
        r = db.connect().execute("SELECT * FROM purchases WHERE key=?",
                                 (key,)).fetchone()
    return dict(r) if r else None


def get(key: str) -> dict:
    """리습이 창을 열 때 부른다. 신청한 적이 없으면 빈 상태를 돌려준다."""
    key = (key or "").strip().upper()
    d = _row(key) or {}
    return {
        "ok": True,
        "requested": bool(d) and d.get("status") == "pending",
        "status": d.get("status", "none"),
        "amount": d.get("amount", settings.price()),
        "bank": settings.bank(),
        "want_invoice": bool(d.get("want_invoice")),
        "invoiced": bool(d.get("invoiced")),
        "machine": d.get("machine", ""),
        **{f: d.get(f, "") or "" for f in FIELDS},
    }


def request(key: str, machine: str, biz: dict, want_invoice: bool) -> dict:
    """신청을 받는다. 같은 키로 다시 보내면 최신 내용으로 덮어쓴다."""
    key = (key or "").strip().upper()
    if not key:
        return {"ok": False, "reason": "발급키가 없습니다."}

    now = time.time()
    with db.lock():
        c = db.connect()
        lic = c.execute("SELECT email, machine FROM licenses WHERE key=?",
                        (key,)).fetchone()
        if not lic:
            return {"ok": False, "reason": "등록되지 않은 발급키입니다."}

        email = lic["email"]
        # PC 번호는 리습이 보낸 것을 우선하되, 없으면 라이선스에 묶인 것을 쓴다
        machine = (machine or lic["machine"] or "")[:120]

        if not (biz.get("contact") or "").strip():
            return {"ok": False,
                    "reason": "연락처를 적어 주세요. 입금 확인과 세금계산서 발송에 씁니다."}

        if want_invoice and not (biz.get("biz_no") or "").strip():
            return {"ok": False,
                    "reason": "세금계산서를 받으시려면 사업자등록번호가 있어야 합니다."}

        vals = {f: (biz.get(f) or "").strip()[:200] for f in FIELDS}
        old = c.execute("SELECT key, invoiced FROM purchases WHERE key=?",
                        (key,)).fetchone()
        if old:
            c.execute(
                "UPDATE purchases SET email=?, machine=?, req_name=?, contact=?,"
                " biz_no=?, biz_name=?, biz_addr=?, biz_type=?, want_invoice=?,"
                " amount=?, status='pending', updated=? WHERE key=?",
                (email, machine, vals["req_name"], vals["contact"],
                 vals["biz_no"], vals["biz_name"], vals["biz_addr"],
                 vals["biz_type"], int(want_invoice), settings.price(), now, key))
        else:
            c.execute(
                "INSERT INTO purchases (key, email, machine, req_name, contact,"
                " biz_no, biz_name, biz_addr, biz_type, want_invoice, amount,"
                " status, created, updated)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?, 'pending', ?, ?)",
                (key, email, machine, vals["req_name"], vals["contact"],
                 vals["biz_no"], vals["biz_name"], vals["biz_addr"],
                 vals["biz_type"], int(want_invoice), settings.price(), now, now))
        c.commit()

    return {"ok": True, "machine": machine, "amount": settings.price(),
            "bank": settings.bank()}


def mark_invoiced(key: str, done: bool = True) -> dict:
    now = time.time()
    with db.lock():
        c = db.connect()
        if not c.execute("SELECT 1 FROM purchases WHERE key=?", (key,)).fetchone():
            return {"ok": False, "reason": "신청 기록이 없습니다."}
        c.execute("UPDATE purchases SET invoiced=?, invoiced_at=?, updated=?"
                  " WHERE key=?",
                  (int(done), now if done else None, now, key))
        c.commit()
    return {"ok": True}


def close(key: str) -> None:
    """정품으로 바꿔 준 뒤 부른다. '신청중' 표시를 내린다."""
    with db.lock():
        c = db.connect()
        c.execute("UPDATE purchases SET status='done', updated=? WHERE key=?",
                  (time.time(), key))
        c.commit()


def by_keys(keys: list[str]) -> dict[str, dict]:
    """관리자 화면에서 여러 키의 신청 상태를 한 번에 가져온다."""
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    with db.lock():
        rows = db.connect().execute(
            f"SELECT * FROM purchases WHERE key IN ({marks})", keys).fetchall()
    return {r["key"]: dict(r) for r in rows}


def pending_count() -> int:
    with db.lock():
        return db.connect().execute(
            "SELECT COUNT(*) FROM purchases WHERE status='pending'").fetchone()[0]
