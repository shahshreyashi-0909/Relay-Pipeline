"""
Thin client for the Claude Messages API.

Uses plain HTTP (requests) so the project has no SDK dependency.
If ANTHROPIC_API_KEY is missing, `available()` returns False and the
planner falls back to the offline template generator in ml/generator.py.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")


class LLMError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def complete(system: str, user: str, *, max_tokens: int = 4000, temperature: float = 0.7,
             model: str | None = None, retries: int = 2) -> str:
    """Return the assistant text for one user turn."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    payload = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                raise LLMError(f"API {r.status_code}: {r.text[:200]}")
            if r.status_code != 200:
                raise LLMError(f"API {r.status_code}: {r.text[:400]}")
            data = r.json()
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        except (requests.RequestException, LLMError) as e:  # retry transient failures
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise LLMError(str(last))


def complete_json(system: str, user: str, **kw) -> Any:
    """Ask for JSON and parse it tolerantly (whole text, a code fence, or first {…}/[…] span)."""
    text = complete(system, user, **kw)
    return parse_json(text)


def parse_json(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if starts:
        s = min(starts)
        e = max(text.rfind("}"), text.rfind("]"))
        if e > s:
            return json.loads(text[s:e + 1])
    raise LLMError("Model reply contained no JSON")
