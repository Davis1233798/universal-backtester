"""One-bar-at-a-time strategy interface. Plugins do NOT see future candles."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import importlib.util
import json
import os
import queue
import shlex
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from .model import iso_ms
from typing import Any


def signal(name: str, ctx: dict, options: dict) -> float:
    bars = ctx["bars"]
    closes = [b["close"] for b in bars]
    if name == "buy_hold":
        return 1.0
    if name == "sma_cross":
        fast, slow = int(options.get("fast", 10)), int(options.get("slow", 30))
        if fast < 1 or slow < fast + 1 or len(closes) < slow:
            return 0.0
        a = sum(closes[-fast:])/fast
        b = sum(closes[-slow:])/slow
        return float(a > b) * 2 - 1 if options.get("long_short", False) else float(a > b)
    if name == "rsi_revert":
        n = int(options.get("period", 14))
        if n < 2 or len(closes) <= n:
            return 0.0
        diffs = [closes[i] - closes[i-1] for i in range(len(closes)-n, len(closes))]
        gain = sum(max(d, 0) for d in diffs) / n
        loss = sum(max(-d, 0) for d in diffs) / n
        rsi = 100 if loss == 0 else 100-100/(1+gain/loss)
        if rsi < float(options.get("buy_below", 30)):
            return 1.0
        if rsi > float(options.get("sell_above", 70)):
            return -1.0 if options.get("long_short", False) else 0.0
        return float(ctx.get("target", 0.0))
    if name == "breakout":
        n = int(options.get("lookback", 20))
        if n < 2 or len(bars) <= n:
            return 0.0
        upper = max(b["high"] for b in bars[-n-1:-1])
        lower = min(b["low"] for b in bars[-n-1:-1])
        if closes[-1] > upper:
            return 1.0
        if closes[-1] < lower:
            return -1.0 if options.get("long_short", False) else 0.0
        return float(ctx.get("target", 0.0))
    raise ValueError(f"Unknown builtin strategy: {name}")


class BuiltinStrategy:
    def __init__(self, name: str, options: dict | None = None):
        self.name, self.options = name, options or {}
    def __call__(self, ctx: dict) -> float:
        return signal(self.name, ctx, self.options)
    def close(self):
        pass


class CsvSignalStrategy:
    """Use signals from any language, including signals exported from Pine Script.
    CSV: ts,target with candle-OPEN UTC timestamp and target observed at candle CLOSE.
    No signal on an input candle means holding the previous target.
    """
    def __init__(self, path: str):
        self.signals = {}
        with Path(path).expanduser().open(newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                raw = r["ts"]
                ts = int(raw) if raw.isdecimal() else iso_ms(raw)
                if ts < 1_000_000_000_000:
                    ts *= 1000
                self.signals[ts] = float(r["target"])
    def __call__(self, ctx: dict) -> float:
        return self.signals.get(ctx["bars"][-1]["ts"], float(ctx["target"]))
    def close(self):
        pass


class PythonStrategy:
    """Trusted Python module. This is intentionally NOT a security sandbox."""
    def __init__(self, path: str):
        src = Path(path).resolve()
        if not src.is_file() or src.suffix != ".py":
            raise ValueError("Python plugin must be an existing .py file")
        spec = importlib.util.spec_from_file_location("ubt_user_strategy", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "on_bar", None)):
            raise ValueError("Python plugin must export on_bar(ctx) -> float")
        self.callback = mod.on_bar
    def __call__(self, ctx: dict) -> float:
        return float(self.callback(ctx))
    def close(self):
        pass


class ProcessStrategy:
    """Persistent JSON-lines stdio plugin; executable may be JS, Go, Rust, C#, R, etc.
    Start only trusted programs. Kills process on timeout; stdout reserved for JSON.
    """
    def __init__(self, command: list[str], timeout: float = 3):
        if not command:
            raise ValueError("strategy command cannot be empty")
        self.timeout = timeout
        self.process = subprocess.Popen(command, text=True, bufsize=1,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL)
        self.responses: queue.Queue[str | None] = queue.Queue()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        for line in self.process.stdout:
            self.responses.put(line)
        self.responses.put(None)

    def __call__(self, ctx: dict) -> float:
        if self.process.poll() is not None:
            raise RuntimeError(f"strategy process exited with {self.process.returncode}")
        try:
            self.process.stdin.write(json.dumps(ctx, allow_nan=False, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
            raw = self.responses.get(timeout=self.timeout)
            if raw is None:
                raise RuntimeError("strategy process closed stdout")
            reply = json.loads(raw)
            return float(reply["target"])
        except queue.Empty as err:
            self.close()
            raise TimeoutError(f"strategy response timed out ({self.timeout}s)") from err
        except (OSError, BrokenPipeError):
            self.close()
            raise

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()


def create_strategy(config: dict):
    kind = config.get("type", "builtin")
    if kind == "builtin":
        return BuiltinStrategy(config.get("name", "sma_cross"), config.get("options", {}))
    if kind == "pine":
        from .pine import PineSubsetStrategy
        return PineSubsetStrategy(config.get("code", ""), config.get("inputs"))
    if kind == "signal_csv":
        return CsvSignalStrategy(config["path"])
    if os.environ.get("UBT_ALLOW_EXEC") != "1":
        raise PermissionError("External strategy execution disabled; set UBT_ALLOW_EXEC=1 only on trusted host")
    if kind == "python":
        return PythonStrategy(config["path"])
    if kind == "process":
        command = config["command"]
        if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
            raise ValueError("command must be array of strings (not a shell string)")
        return ProcessStrategy(command, timeout=float(config.get("timeout", 3)))
    raise ValueError(f"Unsupported strategy type: {kind}")
