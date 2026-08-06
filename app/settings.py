"""관리자가 화면에서 바꾸는 값.

금액·계좌처럼 사업하면서 바뀌는 값은 .env 를 고치고 서버를 다시 띄우게
할 일이 아니다. DB 에 두고, 비어 있으면 .env 값을 쓴다.
"""
from __future__ import annotations

from . import config, db


def _get(key: str) -> str | None:
    with db.lock():
        r = db.connect().execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def set_(key: str, value: str) -> None:
    with db.lock():
        c = db.connect()
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                  " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))
        c.commit()


def price() -> int:
    v = _get("price")
    try:
        return int(v) if v else config.PRICE
    except ValueError:
        return config.PRICE


def bank() -> str:
    return (_get("bank") or "").strip() or config.BANK_INFO
