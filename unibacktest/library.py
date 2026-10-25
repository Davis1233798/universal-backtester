"""Private Pine strategy library with immutable revision history.

The HTTP layer enforces bearer authentication globally. This module never
runs arbitrary strategy code while storing a revision; Pine is parsed only.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .pine import PineSubsetStrategy
from .storage import Store


def _schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS saved_strategies (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          kind TEXT NOT NULL,
          code TEXT NOT NULL DEFAULT '',
          strategy_name TEXT NOT NULL DEFAULT '',
          options_json TEXT NOT NULL DEFAULT '{}',
          revision INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS strategy_revisions (
          strategy_id TEXT NOT NULL,
          revision INTEGER NOT NULL,
          name TEXT NOT NULL,
          kind TEXT NOT NULL,
          code TEXT NOT NULL,
          strategy_name TEXT NOT NULL,
          options_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY(strategy_id, revision)
        );
    """)


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Strategy payload must be an object")
    name = str(payload.get("name", "")).strip()
    kind = payload.get("kind", "pine")
    code = payload.get("code", "")
    strategy_name = payload.get("strategy_name", "") or ""
    options = payload.get("options", {})
    if not 1 <= len(name) <= 120:
        raise ValueError("Strategy name must have 1..120 characters")
    if kind not in ("pine", "builtin"):
        raise ValueError("Unsupported strategy type")
    if not isinstance(options, dict) or len(options) > 30:
        raise ValueError("Options must be a JSON object of <=30 entries")
    if kind == "pine":
        if not isinstance(code, str) or not code.strip() or len(code) > 12000:
            raise ValueError("Pine source must have 1..12000 characters")
        PineSubsetStrategy(code)  # Parser/AST whitelist; does not execute
        strategy_name = ""
    else:
        if strategy_name not in ("sma_cross", "rsi_revert", "breakout", "buy_hold"):
            raise ValueError("Unknown built-in strategy")
        code = ""
    if any(not isinstance(k, str) or len(k) > 80 for k in options):
        raise ValueError("Invalid option key")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in options.values()):
        raise ValueError("Strategy options must contain numeric values")
    return {"name": name, "kind": kind, "code": code,
            "strategy_name": strategy_name, "options_json": json.dumps(options)}


def _decode(row):
    d=dict(row)
    d["options"]=json.loads(d.pop("options_json"))
    return d


def list_strategies(store: Store, limit: int = 100):
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1..500")
    with store.connect() as db:
        _schema(db)
        return [_decode(x) for x in db.execute(
            "SELECT * FROM saved_strategies ORDER BY updated_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()]


def get_strategy(store: Store, sid: str):
    with store.connect() as db:
        _schema(db)
        row=db.execute("SELECT * FROM saved_strategies WHERE id=?",(sid,)).fetchone()
        return _decode(row) if row else None


def save_strategy(store: Store, payload: dict, sid: str | None = None):
    values=_validate(payload)
    now=_timestamp()
    with store.connect() as db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        if sid:
            prev=db.execute("SELECT * FROM saved_strategies WHERE id=?",(sid,)).fetchone()
            if prev is None:
                raise KeyError("Strategy not found")
            revision=prev["revision"]+1
            db.execute("UPDATE saved_strategies SET name=?,kind=?,code=?,strategy_name=?,options_json=?,revision=?,updated_at=? WHERE id=?",
                       (values["name"],values["kind"],values["code"],values["strategy_name"],values["options_json"],revision,now,sid))
        else:
            sid=uuid.uuid4().hex
            revision=1
            db.execute("INSERT INTO saved_strategies VALUES(?,?,?,?,?,?,?,?,?)",
                       (sid,values["name"],values["kind"],values["code"],values["strategy_name"],values["options_json"],revision,now,now))
        db.execute("INSERT INTO strategy_revisions VALUES(?,?,?,?,?,?,?,?)",
                   (sid,revision,values["name"],values["kind"],values["code"],values["strategy_name"],values["options_json"],now))
        row=db.execute("SELECT * FROM saved_strategies WHERE id=?",(sid,)).fetchone()
        return _decode(row)


def delete_strategy(store: Store, sid: str):
    with store.connect() as db:
        _schema(db)
        count=db.execute("DELETE FROM saved_strategies WHERE id=?",(sid,)).rowcount
        if count:
            db.execute("DELETE FROM strategy_revisions WHERE strategy_id=?",(sid,))
        return bool(count)


def revisions(store: Store, sid: str, limit: int = 100):
    if not 1 <= limit <= 300:
        raise ValueError("limit must be 1..300")
    with store.connect() as db:
        _schema(db)
        return [_decode(r) for r in db.execute(
            "SELECT * FROM strategy_revisions WHERE strategy_id=? ORDER BY revision DESC LIMIT ?",(sid,limit)
        ).fetchall()]


def restore_revision(store: Store, sid: str, revision: int):
    with store.connect() as db:
        _schema(db)
        row=db.execute("SELECT * FROM strategy_revisions WHERE strategy_id=? AND revision=?",(sid,revision)).fetchone()
    if not row:
        raise KeyError("Revision not found")
    d=_decode(row)
    return save_strategy(store,d,sid)