"""Persistent daily-job runner. Start as separate process in production."""
from __future__ import annotations
import copy
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .service import execute
from .storage import Store

LOG = logging.getLogger("ubt.scheduler")


def run_due_jobs(store: Store, at: datetime | None = None, hhmm: str = "08:00",
                 tz: str = "Asia/Taipei") -> list[dict]:
    now = (at or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz))
    hour, minute = (int(x) for x in hhmm.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("hhmm must be HH:MM")
    if (now.hour, now.minute) < (hour, minute):
        return []
    day = now.date().isoformat()
    summary = []
    for job in store.jobs(active_only=True):
        if job["last_run_day"] == day:
            continue
        config = copy.deepcopy(job["config"])
        # End-exclusive refresh to NOW. Last incomplete candle discarded by load_bars.
        config.setdefault("data", {})["end"] = now.astimezone(timezone.utc).isoformat()
        config["refresh"] = False
        try:
            report = execute(config, store=store, incremental=True)
            msg = "ok:" + report["run_id"]
        except Exception as err:
            LOG.exception("job %s failed", job["id"])
            msg = "error:" + str(err)[:300]
        store.mark_job(job["id"], day, msg)
        summary.append({"job_id": job["id"], "day": day, "result": msg})
    return summary


def loop(db_path: str | None = None, hhmm: str = "08:00", tz: str = "Asia/Taipei"):
    logging.basicConfig(level=logging.INFO)
    store = Store(db_path)
    LOG.info("daily scheduler started at %s %s", hhmm, tz)
    while True:
        run_due_jobs(store, hhmm=hhmm, tz=tz)
        time.sleep(30)
