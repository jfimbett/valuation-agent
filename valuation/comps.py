"""Trading multiples from peers. Non-positive denominators are excluded and disclosed, never repaired."""
from __future__ import annotations

from statistics import median

from .dcf import ValuationError


def peer_multiples(peers: list[dict]) -> dict:
    """peers: [{ticker, market_cap, net_debt, ebitda, net_income}] in USD millions.
    Returns per-peer multiples, the exclusions with reasons, and the medians."""
    used, excluded = [], []
    for p in peers:
        ev = p["market_cap"] + p["net_debt"]
        row = {"ticker": p["ticker"]}
        for name, num, den in (("ev_ebitda", ev, p["ebitda"]), ("pe", p["market_cap"], p["net_income"])):
            if den is None or den <= 0:
                excluded.append({"ticker": p["ticker"], "multiple": name, "reason": "non-positive or missing denominator"})
            else:
                row[name] = num / den
        used.append(row)
    med = {}
    for name in ("ev_ebitda", "pe"):
        vals = [r[name] for r in used if name in r]
        med[name] = median(vals) if vals else None
    return {"peers": used, "excluded": excluded, "median": med}


def implied_value_per_share(multiples: dict, ebitda: float, net_income: float, net_debt_adj: float,
                            diluted_shares: float) -> dict:
    """net_debt_adj: debt - cash + NCI + preferred - equity-method investments (the bridge minus EV)."""
    if diluted_shares <= 0:
        raise ValuationError("diluted share count missing or non-positive")
    out = {}
    m = multiples["median"]
    if m["ev_ebitda"] is not None and ebitda > 0:
        out["ev_ebitda"] = (m["ev_ebitda"] * ebitda - net_debt_adj) / diluted_shares
    if m["pe"] is not None and net_income > 0:
        out["pe"] = m["pe"] * net_income / diluted_shares
    if not out:
        raise ValuationError("no usable multiple: comparables blocked")
    return out
