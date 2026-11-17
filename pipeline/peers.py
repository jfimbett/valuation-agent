"""Peer selection by financial similarity, in code. The user approves the final list (human gate).

Candidates: companies with the same SIC code on EDGAR that are currently listed (SEC ticker list).
Metrics: market cap, revenue growth, operating margin and leverage from Yahoo (via yfinance); the target's own
numbers come from the same source so the distance is like for like. Weights are in settings.yaml.
"""
from __future__ import annotations

import math
import re

from . import sec

DEFAULT_WEIGHTS = {"size": 1.0, "growth": 1.0, "margin": 1.0, "leverage": 1.0}   # open decision: equal weights


def candidates_by_sic(sic: int, exclude: str, limit: int = 100) -> list[str]:
    """Tickers of listed companies with this SIC code (EDGAR company browse, atom feed)."""
    import json
    listed = {str(r["cik_str"]).zfill(10): r["ticker"]
              for r in json.loads(sec._get("https://www.sec.gov/files/company_tickers.json")).values()}
    ciks = []   # the same SIC code first, then its neighbours in the same three-digit group (e.g. 2080-2089)
    for code in [sic] + [c for c in range(sic // 10 * 10, sic // 10 * 10 + 10) if c != sic]:
        try:
            xml = sec._get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={code}&type=10-K"
                           f"&owner=include&count={limit}&output=atom").decode("latin-1")
        except sec.FetchError:
            continue
        ciks += re.findall(r"<cik>(\d+)</cik>", xml)
    out = [(listed[c], c) for c in ciks if c in listed and listed[c].upper() != exclude.upper()]
    # keep only companies that file 10-Ks (not 20-F/40-F foreign filers): the course supports US 10-K/10-Q filers
    keep = []
    for tkr, cik in dict.fromkeys(out):
        try:
            sub = json.loads(sec._get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
        except sec.FetchError:
            continue
        if "10-K" in sub.get("filings", {}).get("recent", {}).get("form", []):
            keep.append(tkr)
    return keep


def metrics(ticker: str) -> dict | None:
    import yfinance as yf
    try:
        i = yf.Ticker(ticker).info
    except Exception:
        return None
    mc = i.get("marketCap")
    if not mc or mc <= 0:
        return None
    rev = i.get("totalRevenue")
    debt = i.get("totalDebt") or 0
    cash = i.get("totalCash") or 0
    return {"ticker": ticker, "market_cap": mc / 1e6, "net_debt": (debt - cash) / 1e6,
            "ebitda": (i["ebitda"] / 1e6) if i.get("ebitda") else None,
            "net_income": (i["netIncomeToCommon"] / 1e6) if i.get("netIncomeToCommon") else None,
            "revenue": rev / 1e6 if rev else None, "revenue_growth": i.get("revenueGrowth"),
            "operating_margin": i.get("operatingMargins"), "leverage": (debt / 1e6) / (mc / 1e6)}


def distance(a: dict, b: dict, w: dict = DEFAULT_WEIGHTS) -> float | None:
    """Weighted distance on log size, growth, margin and leverage. None if a metric is missing."""
    try:
        parts = {"size": abs(math.log(a["market_cap"]) - math.log(b["market_cap"])),
                 "growth": abs(a["revenue_growth"] - b["revenue_growth"]),
                 "margin": abs(a["operating_margin"] - b["operating_margin"]),
                 "leverage": abs(a["leverage"] - b["leverage"])}
    except (TypeError, KeyError):
        return None
    return sum(w[k] * v for k, v in parts.items())


def rank(target: dict, cands: list[dict], n: int = 5, w: dict = DEFAULT_WEIGHTS) -> dict:
    scored, dropped = [], []
    for c in cands:
        dist = distance(target, c, w)
        (scored if dist is not None else dropped).append((dist, c) if dist is not None else
                                                          {"ticker": c["ticker"], "reason": "missing metric"})
    scored.sort(key=lambda x: x[0])
    return {"selected": [{**c, "distance": round(d, 4)} for d, c in scored[:n]],
            "not_selected": [c["ticker"] for _, c in scored[n:]], "dropped": dropped}


def propose(ticker: str, sic: int | None, n: int = 5) -> dict:
    """Return peers.json content; approved stays False until the user approves the list."""
    if sic is None:
        return {"status": "missing", "reason": "no SIC code", "approved": False}
    tgt = metrics(ticker)
    if tgt is None:
        return {"status": "missing", "reason": "no market data for the target", "approved": False}
    cands = [m for t in candidates_by_sic(sic, ticker)[:40] if (m := metrics(t))]
    r = rank(tgt, cands, n)
    note = None if len(r["selected"]) >= n else f"only {len(r['selected'])} comparable peers found (wanted {n})"
    return {"status": "proposed", "sic": sic, "target": tgt, "approved": False, "note": note, **r}
