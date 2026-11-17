"""SEC retrieval: declared User-Agent, <= 10 requests/second, 3 retries with growing pause, hashed cache.
Only sec.gov hosts are allowed. Downloaded content is parsed as JSON and never executed."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .env import load_env

EVIDENCE = Path(__file__).resolve().parent.parent / "evidence"
ALLOWED = {"data.sec.gov", "www.sec.gov"}
_last = [0.0]


class FetchError(RuntimeError):
    pass


def _get(url: str, retries: int = 3, min_gap: float = 0.11) -> bytes:
    load_env()
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua or "@" not in ua:
        raise FetchError("SEC_USER_AGENT is not set (project name and contact email, see .env.example)")
    if urlparse(url).hostname not in ALLOWED:
        raise FetchError(f"host not allowed: {url}")
    err = ""
    for attempt in range(retries + 1):
        wait = min_gap - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=30)
            if r.status_code == 200:
                return r.content
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = type(e).__name__
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise FetchError(f"{url}: {err} after {retries} retries")


def fetch_cached(url: str, name: str, cik: str, today: str) -> dict:
    """Save the response once under evidence/<CIK>/ with a manifest entry (URL, time, SHA-256, size)."""
    d = EVIDENCE / cik
    d.mkdir(parents=True, exist_ok=True)
    body = _get(url)
    json.loads(body)  # must parse as JSON; never executed
    (d / name).write_bytes(body)
    return {"file": f"evidence/{cik}/{name}", "url": url, "retrieved_at": today,
            "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}


def cik_for(ticker: str) -> str:
    data = json.loads(_get("https://www.sec.gov/files/company_tickers.json"))
    for row in data.values():
        if row["ticker"].upper() == ticker.upper():
            return str(row["cik_str"]).zfill(10)
    raise FetchError(f"ticker not found in SEC list: {ticker}")
