"""SQLite candle cache, run results, and daily jobs; WAL for API + scheduler."""
from __future__ import annotations
import json
import os
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path
from .model import Bar, DataRequest, iso_ms

DEFAULT_DB = os.environ.get("UBT_DB", "./data/backtests.sqlite3")


class Store:
    def __init__(self, path: str | None = None):
        self.path = str(path or DEFAULT_DB)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def initialize(self):
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS candles(
              source_key TEXT NOT NULL, ts INTEGER NOT NULL,
              open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
              close REAL NOT NULL, volume REAL NOT NULL, funding_rate REAL NOT NULL DEFAULT 0,
              PRIMARY KEY(source_key, ts));
            CREATE INDEX IF NOT EXISTS candles_time_idx ON candles(ts);
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              config TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, config TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
              last_run_day TEXT NOT NULL DEFAULT '', last_result TEXT NOT NULL DEFAULT '');
            """)

    def upsert_bars(self, key: str, bars: list[Bar]) -> int:
        with self.connect() as db:
            db.executemany("""INSERT INTO candles
              (source_key,ts,open,high,low,close,volume,funding_rate)
              VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(source_key,ts) DO UPDATE SET
              open=excluded.open,high=excluded.high,low=excluded.low,
              close=excluded.close,volume=excluded.volume,funding_rate=excluded.funding_rate""",
              [(key, b.ts, b.open, b.high, b.low, b.close, b.volume, b.funding_rate) for b in bars])
        return len(bars)

    def get_bars(self, req: DataRequest) -> list[Bar]:
        with self.connect() as db:
            rows = db.execute("""SELECT ts,open,high,low,close,volume,funding_rate FROM candles
                WHERE source_key=? AND ts>=? AND ts<? ORDER BY ts""",
                (req.cache_key(), iso_ms(req.start), iso_ms(req.end))).fetchall()
        return [Bar(**dict(r)) for r in rows]

    def last_ts(self, req: DataRequest) -> int | None:
        with self.connect() as db:
            row = db.execute("SELECT MAX(ts) FROM candles WHERE source_key=?", (req.cache_key(),)).fetchone()
        return row[0]

    def save_run(self, config: dict, result: dict) -> str:
        uid = uuid.uuid4().hex[:16]
        with self.connect() as db:
            db.execute("INSERT INTO runs(id,config,result) VALUES (?,?,?)",
                       (uid, json.dumps(config), json.dumps(result, allow_nan=False)))
        return uid

    def get_run(self, uid: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (uid,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "created_at": row["created_at"],
                "config": json.loads(row["config"]), "result": json.loads(row["result"])}

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,created_at,config,result FROM runs ORDER BY created_at DESC,id DESC LIMIT ?",
                              (max(1,min(limit,100)),)).fetchall()
        return [{"id": r["id"], "created_at": r["created_at"],
                 "config": json.loads(r["config"]), "metrics": json.loads(r["result"])["metrics"]}
                for r in rows]

    def add_job(self, config: dict) -> str:
        uid = uuid.uuid4().hex[:16]
        with self.connect() as db:
            db.execute("INSERT INTO jobs(id,config) VALUES (?,?)", (uid, json.dumps(config)))
        return uid

    def jobs(self, active_only: bool = False) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs" + (" WHERE active=1" if active_only else "") + " ORDER BY rowid DESC").fetchall()
        return [{"id": r["id"], "config": json.loads(r["config"]),
                 "active": bool(r["active"]), "last_run_day": r["last_run_day"],
                 "last_result": r["last_result"]} for r in rows]

    def set_job_active(self, uid: str, active: bool) -> bool:
        with self.connect() as db:
            r = db.execute("UPDATE jobs SET active=? WHERE id=?", (int(active), uid))
            return r.rowcount > 0

    def mark_job(self, uid: str, day: str, result: str):
        with self.connect() as db:
            db.execute("UPDATE jobs SET last_run_day=?,last_result=? WHERE id=?", (day, result, uid))
