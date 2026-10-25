"""Optional server-side AI assistance for draft Pine code.

No API keys are ever sent to a browser or embedded in frontend bundles.
Generated code must pass the existing Pine subset parser, and is NEVER
executed, saved or deployed automatically.
"""
from __future__ import annotations

import os
import re

import httpx

from .pine import PineSubsetStrategy

_ALLOWED_PROMPT = (
    "Generate ONLY Pine Script strategy source compatible with the restricted "
    "Universal Backtester interpreter. Return code, no markdown. "
    "Start with //@version=6 and strategy(\"Name\"). "
    "Supported: input.int, ta.sma, ta.ema, ta.rsi, ta.highest, ta.lowest, "
    "ta.crossover, ta.crossunder, close/open/high/low, simple if statements, "
    "strategy.entry, strategy.close, strategy.close_all, "
    "strategy.exit(stop=price,limit=price). "
    "Do not use request.security, arrays, function declarations, loops, "
    "strategy.exit qty/trailing, or unsupported Pine functions. "
    "Ensure no future data leakage or lookahead."
)


async def generate_pine(description: str) -> dict:
    if not isinstance(description, str) or not 12 <= len(description.strip()) <= 2000:
        raise ValueError("Description must have 12..2000 characters")
    secret = os.environ.get("UBT_AI_API_KEY", "")
    if not secret:
        raise RuntimeError("AI generator is not configured: set private UBT_AI_API_KEY")
    model = os.environ.get("UBT_AI_MODEL", "gpt-4.1-mini")
    if not model or len(model) > 80:
        raise ValueError("Invalid UBT_AI_MODEL setting")
    payload = {
        "model": model,
        "messages": [
            {"role": "developer", "content": _ALLOWED_PROMPT},
            {"role": "user", "content": description.strip()}
        ],
        "max_completion_tokens": 2000
    }
    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer " + secret},
        )
        response.raise_for_status()
        data = response.json()
    message = data["choices"][0]["message"]["content"]
    if not isinstance(message, str):
        raise ValueError("AI did not generate textual strategy code")
    source = re.sub(r"^\s*```(?:pine|pinescript)?\s*\n", "", message.strip(), flags=re.I)
    source = re.sub(r"\n\s*```\s*$", "", source).strip()
    if len(source) > 12000:
        raise ValueError("Generated strategy exceeds the 12k restricted parser limit")
    try:
        PineSubsetStrategy(source)
    except (ValueError, SyntaxError, TypeError) as exc:
        raise ValueError("Generated Pine is not supported by this interpreter: " + str(exc)) from exc
    return {"code": source, "model": model, "validated_subset": True,
            "notice": "Generated code has only been parsed; review and backtest before using."}
