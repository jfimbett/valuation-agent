"""Step 1, fetch: SEC company facts and submissions, Yahoo market data (via yfinance), risk-free rate.

Usage: python -m pipeline.fetch <TICKER> <DATE>      (run folder must exist: python -m pipeline start ...)
Writes runs/<TICKER>/<DATE>/evidence.json: a manifest of saved files, the market data and the refusal check.
A value that cannot be fetched is recorded as missing with a reason; nothing is filled in.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
import yaml

from . import peers, run, sec
from .env import load_env

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = yaml.safe_load((ROOT / "settings.yaml").read_text())


def refusal(sic: int | None) -> str | None:
    """Banks, insurers and REITs need their own models: refuse with a message."""
    if sic is None:
        return None
    if 6000 <= sic <= 6411:
        return "banks, brokers and insurers are not supported (a different valuation model is needed)"
    if sic == 6798:
        return "REITs are not supported (a different valuation model is needed)"
    return None


def risk_free(as_of: str) -> dict:
    """FRED 10-year Treasury (DGS10) if FRED_API_KEY is set; otherwise the manual value in settings.yaml."""
    load_env()
    key = os.environ.get("FRED_API_KEY")
    if key:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": "DGS10", "api_key": key, "file_type": "json",
                                 "observation_end": as_of, "sort_order": "desc", "limit": 10}, timeout=30)
        r.raise_for_status()
        for o in r.json()["observations"]:
            if o["value"] not in (".", ""):
                return {"value": float(o["value"]) / 100, "source": "FRED DGS10", "date": o["date"],
                        "notice": "This product uses the FRED(R) API but is not endorsed or certified by the "
                                  "Federal Reserve Bank of St. Louis."}
        return {"value": None, "reason": "FRED returned no observation"}
    manual = SETTINGS["discount_rate"].get("risk_free_rate_manual")
    if manual is None:
        return {"value": None, "reason": "no FRED_API_KEY and no risk_free_rate_manual in settings.yaml"}
    return {"value": manual, "source": "settings.yaml (manual)", "date": None,
            "warning": "risk-free rate was typed in by hand, not fetched"}


def market(ticker: str, as_of: str) -> dict:
    """Price, market cap and a 5-year monthly beta against the S&P 500, from Yahoo via yfinance (research use)."""
    import yfinance as yf
    import numpy as np

    end = date.fromisoformat(as_of)
    start = end - timedelta(days=365 * 5 + 40)
    try:
        px = yf.download([ticker, "^GSPC"], start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                         interval="1mo", auto_adjust=True, progress=False)["Close"].dropna()
        rets = px.pct_change().dropna().tail(60)
        if len(rets) < 36:
            return {"value": None, "reason": f"only {len(rets)} monthly returns"}
        cov = np.cov(rets[ticker], rets["^GSPC"])
        beta = float(cov[0, 1] / cov[1, 1])
        last = yf.download(ticker, start=(end - timedelta(days=10)).isoformat(),
                           end=(end + timedelta(days=1)).isoformat(), progress=False, auto_adjust=False)["Close"].dropna()
        price = float(last.iloc[-1].iloc[0] if hasattr(last.iloc[-1], "iloc") else last.iloc[-1])
        return {"beta": beta, "beta_months": int(len(rets)), "price": price,
                "price_date": str(last.index[-1].date()), "source": "Yahoo Finance via yfinance",
                "notice": "yfinance is not affiliated with Yahoo; research and educational use only."}
    except Exception as e:  # network or data problems are recorded, not hidden
        return {"value": None, "reason": f"{type(e).__name__}: {e}"}


def main(ticker: str, as_of: str) -> None:
    d = run.run_dir(ticker, as_of)
    cik = sec.cik_for(ticker)
    files = [sec.fetch_cached(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", "companyfacts.json", cik, as_of),
             sec.fetch_cached(f"https://data.sec.gov/submissions/CIK{cik}.json", "submissions.json", cik, as_of)]
    sub = json.loads((ROOT / files[1]["file"]).read_text())
    sic = int(sub["sic"]) if sub.get("sic") else None
    out = {"ticker": ticker.upper(), "cik": cik, "name": sub.get("name"), "sic": sic,
           "sic_description": sub.get("sicDescription"), "valuation_date": as_of, "files": files,
           "refused": refusal(sic), "risk_free": risk_free(as_of), "market": market(ticker.upper(), as_of)}
    (d / "evidence.json").write_text(json.dumps(out, indent=2))
    if not out["refused"]:
        (d / "peers.json").write_text(json.dumps(peers.propose(ticker.upper(), sic, SETTINGS["peers"]["count"]), indent=2))
    run.log(d, event="fetch", files=[f["sha256"][:12] for f in files], refused=out["refused"])
    if out["refused"]:
        run.block(d, out["refused"])
    print(f"saved {d / 'evidence.json'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
