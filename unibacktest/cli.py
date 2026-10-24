from __future__ import annotations
import argparse
import json
from .adapters import fetch
from .model import DataRequest
from .scheduler import loop, run_due_jobs
from .service import execute
from .storage import Store


def main():
    p = argparse.ArgumentParser(prog="ubt", description="Multi-market historical backtest")
    p.add_argument("--db", default=None, help="SQLite file path")
    sub = p.add_subparsers(dest="cmd", required=True)
    demo = sub.add_parser("demo", help="Run deterministic synthetic demo")
    backtest = sub.add_parser("backtest", help="Read config JSON and run once")
    backtest.add_argument("config", help="Path to config.json")
    backtest.add_argument("--no-save", action="store_true")
    job = sub.add_parser("add-job", help="Persist config as daily job")
    job.add_argument("config")
    sub.add_parser("jobs", help="List jobs")
    once = sub.add_parser("run-due", help="Run due scheduled jobs once")
    sched = sub.add_parser("scheduler", help="Run daemon loop for daily jobs")
    for parser in (once, sched):
        parser.add_argument("--time", default="08:00", help="Local HH:MM")
        parser.add_argument("--tz", default="Asia/Taipei", help="IANA timezone")
    args = p.parse_args()
    store = Store(args.db)
    if args.cmd == "demo":
        config = {"data":{"provider":"demo","symbol":"SYNTHETIC", "start":"2024-01-01", "end":"2025-01-01"},
                  "strategy":{"type":"builtin","name":"sma_cross","options":{"fast":10,"slow":30}},
                  "risk":{"product_type":"spot","leverage":1}}
        output = execute(config, store=store)
        print(json.dumps({"run_id":output["run_id"], "metrics":output["metrics"],
                          "warnings":["SYNTHETIC DEMO DATA"]}, indent=2))
    elif args.cmd == "backtest":
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)
        output = execute(config, store=store, save=not args.no_save)
        print(json.dumps({"run_id":output.get("run_id"),"metrics":output["metrics"],
                          "coverage":output["coverage"],"warnings":output["warnings"]}, indent=2))
    elif args.cmd == "add-job":
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)
        print(store.add_job(config))
    elif args.cmd == "jobs":
        print(json.dumps(store.jobs(), indent=2))
    elif args.cmd == "run-due":
        print(json.dumps(run_due_jobs(store, hhmm=args.time,tz=args.tz), indent=2))
    elif args.cmd == "scheduler":
        loop(args.db, args.time, args.tz)

if __name__ == "__main__":
    main()
