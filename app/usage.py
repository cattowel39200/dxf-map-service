"""사용 기록.

추출 작업 한 건마다 결과를 남긴다. 로그인이 없는 공개 서비스라 누가 얼마나
쓰는지 볼 수 있어야 남용을 알아챌 수 있다.

SQLite 파일 하나만 쓴다. 별도 DB 서버가 필요 없고, 서버를 다시 띄워도 기록이
남는다. 초당 수십 건 수준까지는 이걸로 충분하다.
"""
import sqlite3
import threading
import time
from pathlib import Path

from . import config

_lock = threading.Lock()
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
"""


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.USAGE_DB.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.USAGE_DB, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def record(job, meta: dict):
    """작업이 끝났을 때 한 번 부른다. 기록 실패가 서비스를 막지 않게 한다."""
    try:
        with _lock:
            _db().execute(
                "INSERT OR REPLACE INTO jobs (id, created, ip, source, crs, layers,"
                " area_km2, lon, lat, parcels, objects, size, elapsed, state, error)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job.id, job.created, meta.get("ip"), meta.get("source"),
                 meta.get("crs"), ",".join(meta.get("layers") or []),
                 meta.get("area_km2"), meta.get("lon"), meta.get("lat"),
                 job.parcel_count,
                 sum(l["count"] for l in job.layers) if job.layers else 0,
                 job.size, job.elapsed, job.state, job.error[:300] or None),
            )
            _db().commit()
    except sqlite3.Error:
        pass


def record_download(job_id: str, ip: str | None):
    try:
        with _lock:
            _db().execute("INSERT INTO downloads (job_id, at, ip) VALUES (?,?,?)",
                          (job_id, time.time(), ip))
            _db().commit()
    except sqlite3.Error:
        pass


def stats(days: int = 30) -> dict:
    """대시보드에 뿌릴 집계."""
    now = time.time()
    day = 86400
    with _lock:
        c = _db()

        def one(sql, *a):
            r = c.execute(sql, tuple(a)).fetchone()
            return dict(r) if r else {}

        total = one(
            "SELECT COUNT(*) n,"
            " SUM(state='done') ok,"
            " SUM(state='error') err,"
            " COALESCE(SUM(parcels),0) parcels,"
            " COALESCE(SUM(size),0) bytes,"
            " COALESCE(AVG(CASE WHEN state='done' THEN elapsed END),0) avg_sec"
            " FROM jobs")
        today = one("SELECT COUNT(*) n FROM jobs WHERE created > ?", now - day)
        week = one("SELECT COUNT(*) n FROM jobs WHERE created > ?", now - 7 * day)
        users = one("SELECT COUNT(DISTINCT ip) n FROM jobs WHERE created > ?",
                    now - 30 * day)

        daily = [dict(r) for r in c.execute(
            "SELECT CAST((?-created)/86400 AS INT) ago, COUNT(*) n,"
            " SUM(state='error') err"
            " FROM jobs WHERE created > ? GROUP BY ago ORDER BY ago",
            (now, now - days * day))]

        by_crs = [dict(r) for r in c.execute(
            "SELECT crs, COUNT(*) n FROM jobs GROUP BY crs ORDER BY n DESC LIMIT 10")]
        by_source = [dict(r) for r in c.execute(
            "SELECT COALESCE(source,'?') source, COUNT(*) n FROM jobs"
            " GROUP BY source ORDER BY n DESC")]
        top_ip = [dict(r) for r in c.execute(
            "SELECT ip, COUNT(*) n, MAX(created) last FROM jobs"
            " WHERE created > ? GROUP BY ip ORDER BY n DESC LIMIT 10", (now - 30 * day,))]
        errors = [dict(r) for r in c.execute(
            "SELECT error, COUNT(*) n FROM jobs WHERE state='error' AND error IS NOT NULL"
            " GROUP BY error ORDER BY n DESC LIMIT 8")]
        recent = [dict(r) for r in c.execute(
            "SELECT id, created, ip, source, crs, area_km2, lon, lat, parcels,"
            " size, elapsed, state, error FROM jobs ORDER BY created DESC LIMIT 50")]
        dl = one("SELECT COUNT(*) n FROM downloads")

    # 일자별을 빠짐없이 채운다(기록 없는 날은 0)
    m = {d["ago"]: d for d in daily}
    series = [{"ago": i, "n": m.get(i, {}).get("n", 0),
               "err": m.get(i, {}).get("err", 0) or 0} for i in range(days)]
    series.reverse()

    return {
        "total": total, "today": today.get("n", 0), "week": week.get("n", 0),
        "users_30d": users.get("n", 0), "downloads": dl.get("n", 0),
        "daily": series, "by_crs": by_crs, "by_source": by_source,
        "top_ip": top_ip, "errors": errors, "recent": recent,
        "now": now,
    }
