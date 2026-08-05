"""서비스 데이터 저장소.

사용 기록·공지사항·신청자·라이선스를 SQLite 파일 하나에 담는다. 별도 DB
서버가 필요 없고 서버를 다시 띄워도 남는다. 이 규모에서는 이걸로 충분하다.
"""
import sqlite3
import threading

from . import config

# 같은 스레드가 중첩해 잠가도 멈추지 않도록 재진입 락을 쓴다.
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    created     REAL NOT NULL,
    ip          TEXT,
    source      TEXT,              -- web | cad
    crs         TEXT,
    layers      TEXT,
    area_km2    REAL,
    lon         REAL,
    lat         REAL,
    parcels     INTEGER,
    objects     INTEGER,
    size        INTEGER,
    elapsed     REAL,
    state       TEXT,              -- done | error
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created);

CREATE TABLE IF NOT EXISTS downloads (
    job_id  TEXT,
    at      REAL,
    ip      TEXT
);

CREATE TABLE IF NOT EXISTS notices (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    title    TEXT NOT NULL,
    body     TEXT NOT NULL DEFAULT '',
    kind     TEXT NOT NULL DEFAULT 'info',   -- info | warn | event
    active   INTEGER NOT NULL DEFAULT 1,
    popup    INTEGER NOT NULL DEFAULT 1,     -- 접속 시 팝업으로 띄울지
    starts   REAL,                           -- 비우면 즉시
    ends     REAL,                           -- 비우면 무기한
    created  REAL NOT NULL,
    updated  REAL
);
CREATE INDEX IF NOT EXISTS idx_notices_active ON notices(active, created);
"""


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.USAGE_DB.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.USAGE_DB, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def lock() -> threading.RLock:
    return _lock
