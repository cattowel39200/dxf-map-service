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

-- 사용 신청자. 이메일 하나가 곧 한 사람이다.
CREATE TABLE IF NOT EXISTS applicants (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    email     TEXT NOT NULL UNIQUE,
    name      TEXT,
    company   TEXT,
    memo      TEXT,
    ip        TEXT,
    created   REAL NOT NULL,
    sent_demo REAL,                      -- 데모 발송 시각
    sent_full REAL,                      -- 정품 발송 시각
    status    TEXT NOT NULL DEFAULT 'new'  -- new | demo | paid | blocked
);

-- 발급 라이선스. 리습이 이 키를 들고 서버에 물어본다.
CREATE TABLE IF NOT EXISTS licenses (
    key        TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'demo',   -- demo | full
    issued     REAL NOT NULL,
    first_use  REAL,                  -- 처음 쓴 시각. 데모 만료는 여기서부터 센다
    expires    REAL,                  -- 정품은 비움(무기한)
    machine    TEXT,                  -- 처음 쓴 PC 지문. 이후 다른 PC는 거부
    machine_at REAL,
    last_use   REAL,
    uses       INTEGER NOT NULL DEFAULT 0,
    revoked    INTEGER NOT NULL DEFAULT 0,
    note       TEXT
);
CREATE INDEX IF NOT EXISTS idx_lic_email ON licenses(email);

-- 정품 구매 신청. 리습의 '정품신청' 창에서 보낸 것이 여기 쌓인다.
-- 발급키 하나에 신청 하나. 다시 신청하면 덮어쓴다.
CREATE TABLE IF NOT EXISTS purchases (
    key          TEXT PRIMARY KEY,
    email        TEXT,
    machine      TEXT,                 -- 입금자명으로 쓰는 PC 번호
    biz_no       TEXT,                 -- 사업자등록번호
    biz_name     TEXT,                 -- 상호
    biz_addr     TEXT,                 -- 주소
    biz_type     TEXT,                 -- 업종
    req_name     TEXT,                 -- 신청자 이름
    contact      TEXT,                 -- 연락처(메일 또는 전화)
    want_invoice INTEGER NOT NULL DEFAULT 0,   -- 세금계산서를 원하는지
    invoiced     INTEGER NOT NULL DEFAULT 0,   -- 발급을 마쳤는지
    invoiced_at  REAL,
    amount       INTEGER NOT NULL DEFAULT 44000,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | done | cancel
    created      REAL NOT NULL,
    updated      REAL
);
CREATE INDEX IF NOT EXISTS idx_pur_status ON purchases(status, created);

-- 관리자가 화면에서 바꾸는 값 (금액·계좌). 비면 .env 를 쓴다.
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

-- PC 이전 이력. 자가 이전이 잦으면 여기서 드러난다.
CREATE TABLE IF NOT EXISTS transfers (
    key      TEXT NOT NULL,
    at       REAL NOT NULL,
    old_pc   TEXT,
    new_pc   TEXT,
    by_admin INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tr_key ON transfers(key, at);
"""


# 나중에 늘린 칸. CREATE TABLE IF NOT EXISTS 는 이미 있는 표를 고치지 않으므로
# 여기에 적어 두고 없으면 붙인다. 운영 중인 자료를 지우지 않고 넘어가려는 것이다.
ADDED_COLUMNS = [
    ("purchases", "req_name", "TEXT"),   # 신청자 이름
    ("purchases", "contact", "TEXT"),    # 연락처
]


def _migrate(c: sqlite3.Connection) -> None:
    for table, col, kind in ADDED_COLUMNS:
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        if have and col not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.USAGE_DB.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.USAGE_DB, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _migrate(_conn)
        _conn.commit()
    return _conn


def lock() -> threading.RLock:
    return _lock
