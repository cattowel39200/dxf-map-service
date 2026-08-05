"""신청자 접수와 라이선스.

리습은 서버에 접속해야만 지적도를 받을 수 있으므로, 라이선스를 파일에 넣지
않고 서버가 판단한다. 덕분에 데모→정품 전환에 파일이나 키를 다시 보낼 필요가
없고, PC 한 대로 제한하는 것도 서버에서 확실히 할 수 있다.

발급키는 사람이 옮겨 적기 쉽게 KS-XXXX-XXXX-XXXX 꼴로 만든다.
"""
import re
import secrets
import time

from . import config, db

# 헷갈리는 글자(0/O, 1/I)는 뺐다. 전화로 불러 줄 일이 있다.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def valid_email(v: str) -> bool:
    return bool(v) and len(v) <= 200 and bool(EMAIL_RE.match(v.strip()))


def _new_key() -> str:
    g = lambda: "".join(secrets.choice(_ALPHABET) for _ in range(4))  # noqa: E731
    return f"KS-{g()}-{g()}-{g()}"


# ── 신청자 ────────────────────────────────────────────────
def apply(email: str, name: str = "", company: str = "",
          memo: str = "", ip: str | None = None) -> dict:
    """사용 신청. 같은 메일로 다시 넣으면 기존 신청을 살린다."""
    email = email.strip().lower()
    now = time.time()
    with db.lock():
        c = db.connect()
        row = c.execute("SELECT id FROM applicants WHERE email=?", (email,)).fetchone()
        if row:
            c.execute("UPDATE applicants SET name=COALESCE(NULLIF(?,''),name),"
                      " company=COALESCE(NULLIF(?,''),company),"
                      " memo=COALESCE(NULLIF(?,''),memo), ip=? WHERE id=?",
                      (name, company, memo, ip, row["id"]))
            aid = row["id"]
            again = True
        else:
            cur = c.execute(
                "INSERT INTO applicants (email, name, company, memo, ip, created, status)"
                " VALUES (?,?,?,?,?,?, 'new')",
                (email, name.strip(), company.strip(), memo.strip(), ip, now))
            aid = cur.lastrowid
            again = False
        c.commit()
    out = get_applicant(aid)
    out["already"] = again
    return out


def get_applicant(aid: int) -> dict | None:
    with db.lock():
        r = db.connect().execute("SELECT * FROM applicants WHERE id=?", (aid,)).fetchone()
    return dict(r) if r else None


def list_applicants() -> list[dict]:
    """신청자 목록에 각자의 라이선스 상태를 붙여 준다."""
    with db.lock():
        c = db.connect()
        rows = c.execute("SELECT * FROM applicants ORDER BY created DESC LIMIT 500").fetchall()
        lic = {}
        for l in c.execute("SELECT * FROM licenses ORDER BY issued").fetchall():
            lic.setdefault(l["email"], []).append(dict(l))
    out = []
    for r in rows:
        d = dict(r)
        d["licenses"] = [_lic_view(x) for x in lic.get(d["email"], [])]
        out.append(d)
    return out


def set_status(aid: int, status: str) -> dict | None:
    if status not in ("new", "demo", "paid", "blocked"):
        return None
    with db.lock():
        c = db.connect()
        c.execute("UPDATE applicants SET status=? WHERE id=?", (status, aid))
        c.commit()
    return get_applicant(aid)


def delete_applicant(aid: int) -> bool:
    with db.lock():
        c = db.connect()
        cur = c.execute("DELETE FROM applicants WHERE id=?", (aid,))
        c.commit()
        return cur.rowcount > 0


# ── 라이선스 ──────────────────────────────────────────────
def issue(email: str, kind: str = "demo", note: str = "",
          reuse: bool = True) -> dict:
    """키를 발급한다.

    reuse=True(기본)이고 이미 쓸 수 있는 키가 있으면 그 키를 그대로 쓴다.
    데모를 쓰던 사람에게 정품을 보낼 때 키가 바뀌면, 안내문("쓰던 키가 그대로
    정품이 됩니다")과 어긋나고 고객도 어느 키를 써야 할지 헷갈린다.
    일부러 새 키가 필요하면(키 분실·유출 등) reuse=False 로 부른다.
    """
    email = email.strip().lower()
    kind = "full" if kind == "full" else "demo"
    now = time.time()

    if reuse:
        exist = _latest_usable(email)
        if exist:
            # 정품 요청이면 등급만 올린다. 키도 PC 등록도 그대로 둔다.
            if kind == "full" and exist["kind"] != "full":
                return upgrade(exist["key"])
            if kind == exist["kind"]:
                _touch_applicant(email, kind, now)
                return get_license(exist["key"])

    key = _new_key()
    with db.lock():
        c = db.connect()
        c.execute("INSERT INTO licenses (key, email, kind, issued, note)"
                  " VALUES (?,?,?,?,?)", (key, email, kind, now, note))
        # 신청자 상태도 함께 옮긴다
        c.execute("UPDATE applicants SET status=?,"
                  " sent_demo=CASE WHEN ?='demo' THEN ? ELSE sent_demo END,"
                  " sent_full=CASE WHEN ?='full' THEN ? ELSE sent_full END"
                  " WHERE email=?",
                  ("paid" if kind == "full" else "demo", kind, now, kind, now, email))
        c.commit()
    return get_license(key)


def _latest_usable(email: str) -> dict | None:
    """중지되지 않은 가장 최근 키. 없으면 None."""
    with db.lock():
        r = db.connect().execute(
            "SELECT * FROM licenses WHERE email=? AND revoked=0"
            " ORDER BY (kind='full') DESC, issued DESC LIMIT 1", (email,)).fetchone()
    return dict(r) if r else None


def _touch_applicant(email: str, kind: str, now: float) -> None:
    col = "sent_full" if kind == "full" else "sent_demo"
    with db.lock():
        c = db.connect()
        c.execute(f"UPDATE applicants SET status=?, {col}=? WHERE email=?",
                  ("paid" if kind == "full" else "demo", now, email))
        c.commit()


def upgrade(key: str) -> dict | None:
    """데모를 정품으로 바꾼다. 키도 파일도 그대로 두고 제한만 푼다."""
    with db.lock():
        c = db.connect()
        c.execute("UPDATE licenses SET kind='full', expires=NULL, revoked=0 WHERE key=?",
                  (key,))
        r = c.execute("SELECT email FROM licenses WHERE key=?", (key,)).fetchone()
        if r:
            c.execute("UPDATE applicants SET status='paid', sent_full=? WHERE email=?",
                      (time.time(), r["email"]))
        c.commit()
    return get_license(key)


def revoke(key: str, on: bool = True) -> dict | None:
    with db.lock():
        c = db.connect()
        c.execute("UPDATE licenses SET revoked=? WHERE key=?", (1 if on else 0, key))
        c.commit()
    return get_license(key)


def reset_machine(key: str) -> dict | None:
    """PC를 바꿨을 때 관리자가 묶임을 풀어 준다."""
    with db.lock():
        c = db.connect()
        c.execute("UPDATE licenses SET machine=NULL, machine_at=NULL WHERE key=?", (key,))
        c.commit()
    return get_license(key)


def get_license(key: str) -> dict | None:
    with db.lock():
        r = db.connect().execute("SELECT * FROM licenses WHERE key=?",
                                 (key.strip().upper(),)).fetchone()
    return _lic_view(dict(r)) if r else None


def _lic_view(d: dict) -> dict:
    d = dict(d)
    d["revoked"] = bool(d.get("revoked"))
    d["expires_at"] = _expiry(d)
    d["expired"] = bool(d["expires_at"] and time.time() > d["expires_at"])
    return d


def _expiry(d: dict) -> float | None:
    """데모 만료 시각. 처음 쓴 때부터 DEMO_DAYS 일."""
    if d.get("kind") == "full":
        return d.get("expires")
    if d.get("expires"):
        return d["expires"]
    if d.get("first_use"):
        return d["first_use"] + config.DEMO_DAYS * 86400
    return None      # 아직 안 썼으면 만료 없음


def check(key: str, machine: str | None) -> dict:
    """리습이 추출을 요청할 때 부른다.

    returns {"ok": bool, "reason": str, "kind": str, "expires_at": float|None,
             "days_left": float|None}
    """
    key = (key or "").strip().upper()
    if not key:
        return {"ok": False, "reason": "발급키가 없습니다. 지도설정에서 입력하세요."}

    now = time.time()
    with db.lock():
        c = db.connect()
        r = c.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
        if not r:
            return {"ok": False, "reason": "등록되지 않은 발급키입니다."}
        d = dict(r)

        if d["revoked"]:
            return {"ok": False, "reason": "사용이 중지된 키입니다. 관리자에게 문의하세요."}

        # PC 묶기 — 처음 쓴 PC를 기억하고 이후 다른 PC는 막는다
        if machine:
            if not d["machine"]:
                c.execute("UPDATE licenses SET machine=?, machine_at=? WHERE key=?",
                          (machine, now, key))
                d["machine"] = machine
            elif d["machine"] != machine:
                c.commit()
                return {"ok": False,
                        "reason": "다른 PC에 등록된 키입니다. 1대에서만 쓸 수 있습니다."}

        if not d["first_use"]:
            c.execute("UPDATE licenses SET first_use=? WHERE key=?", (now, key))
            d["first_use"] = now

        exp = _expiry(d)
        if exp and now > exp:
            c.commit()
            return {"ok": False, "kind": d["kind"], "expires_at": exp,
                    "reason": "데모 기간이 끝났습니다. 정품 구매 후 이용해 주세요."}

        c.execute("UPDATE licenses SET last_use=?, uses=uses+1 WHERE key=?", (now, key))
        c.commit()

    return {
        "ok": True, "kind": d["kind"], "expires_at": exp,
        "days_left": round((exp - now) / 86400, 2) if exp else None,
        "reason": "",
    }
