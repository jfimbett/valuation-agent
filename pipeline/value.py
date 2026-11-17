"""Step 6, value (Python only): DCF for three cases, bridge, comparables, sensitivity. No model, no network.

Usage: python -m pipeline.value <TICKER> <DATE>
Refuses to run unless checks.json has no block and the assumptions were approved at the gate.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from valuation.bridge import Bridge
from valuation.comps import implied_value_per_share, peer_multiples
from valuation.dcf import ValuationError, YearDrivers, capm, enterprise_value, project_fcff, sensitivity_wacc_g, wacc

from . import checks as ck
from . import run
from .history import operating_nwc

ROOT = Path(__file__).resolve().parent.parent


def _v(facts: dict, section: str, key: str) -> float:
    return (facts[section].get(key) or {}).get("value") or 0.0


def drivers_for(assumptions: dict, scenario: str) -> list[YearDrivers]:
    have = {(i["scenario"], i["year"], i["driver"]): i["value"] for i in assumptions["items"]}
    return [YearDrivers(*(have[(scenario, y, dr)] for dr in ck.DRIVERS)) for y in ck.YEARS]


def compute(facts: dict, history: dict, evidence: dict, assumptions: dict, peers: dict | None, settings: dict) -> dict:
    rf = evidence["risk_free"]["value"]
    beta = evidence["market"]["beta"]
    price = evidence["market"]["price"]
    erp = settings["discount_rate"]["equity_risk_premium"]
    sh = facts["diluted_shares"]["value"]
    cover = facts["shares_outstanding"]["value"]
    market_cap = price * cover

    debt = _v(facts, "balance", "debt_long") + _v(facts, "balance", "debt_short") + _v(facts, "balance", "short_term_borrowings")
    cash = _v(facts, "balance", "cash") + _v(facts, "balance", "short_term_investments")
    interest = (facts["ttm"].get("interest_expense") or {}).get("value") or (facts["annual"]["interest_expense"][0]["value"]
                                                                          if facts["annual"].get("interest_expense") else 0.0)
    kd = interest / debt if debt else 0.0
    ke = capm(rf, beta, erp)
    tax_wacc = assumptions_tax(assumptions)
    w = wacc(market_cap, debt, ke, kd, tax_wacc)
    g = assumptions["terminal_growth"]["value"]

    base_rev = (facts["ttm"].get("revenue") or {}).get("value") or facts["annual"]["revenue"][0]["value"]
    nwc0 = operating_nwc(facts)
    if nwc0 is None:
        raise ValuationError("operating working capital cannot be computed from the balance sheet")
    bridge = Bridge(debt=debt, cash=cash, noncontrolling_interests=_v(facts, "balance", "noncontrolling_interests"),
                    equity_method_investments=_v(facts, "balance", "equity_method_investments"),
                    as_of=facts["balance_date"], diluted_shares=sh)

    ronic_setting = settings.get("terminal_return_on_new_capital", "wacc")
    ronic = None if ronic_setting == "wacc" else float(ronic_setting)
    cases = {}
    for s in ck.SCENARIOS:
        rows = project_fcff(base_rev, nwc0, drivers_for(assumptions, s))
        fc = [r["fcff"] for r in rows]
        e = enterprise_value(fc, w, g, rows[-1]["nopat"], ronic)
        cases[s] = {"fcff": fc, "nopat_year5": rows[-1]["nopat"], **e, "equity_value": bridge.equity_value(e["ev"]), "per_share": bridge.per_share(e["ev"])}

    base_fc, base_nopat = cases["base"]["fcff"], cases["base"]["nopat_year5"]
    waccs = [w + d for d in (-0.01, -0.005, 0, 0.005, 0.01)]
    gs = [g + d for d in (-0.01, -0.005, 0, 0.005, 0.01)]
    sens = {"waccs": waccs, "gs": gs, "per_share": sensitivity_wacc_g(base_fc, waccs, gs, bridge.per_share, base_nopat, ronic)}

    # Second grid: the terminal judgment that matters most. Rows: return on new capital (None = equal to the WACC of that
    # column, i.e. growth adds no value); columns: WACC. Values per share, base case.
    ronic_rows = [None] + [x for x in (0.08, 0.10, 0.12, 0.15) if x > g]
    ronic_grid = []
    for rr in ronic_rows:
        row = []
        for ww in waccs:
            try:
                row.append(None if ww <= g else bridge.per_share(enterprise_value(base_fc, ww, g, base_nopat, rr)["ev"]))
            except ValuationError:
                row.append(None)
        ronic_grid.append(row)
    sens["ronic_x_wacc"] = {"ronics": ronic_rows, "waccs": waccs, "per_share": ronic_grid,
                            "note": "ronic null = equal to the WACC of the column (growth adds no value)"}

    out = {"valuation_date": facts["valuation_date"], "unit": "USD_m", "balance_date": facts["balance_date"],
           "wacc": {"wacc": w, "cost_equity": ke, "cost_debt": kd, "tax_rate": tax_wacc, "risk_free": rf, "beta": beta,
                    "erp": erp, "market_cap": market_cap, "debt": debt, "weights_equity": market_cap / (market_cap + debt)},
           "terminal_growth": g, "terminal_return_on_new_capital": ronic_setting, "base_revenue": base_rev, "base_operating_nwc": nwc0, "cases": cases,
           "bridge": {"debt": debt, "cash": cash, "net_debt": bridge.net_debt(),
                      "noncontrolling_interests": bridge.noncontrolling_interests,
                      "equity_method_investments": bridge.equity_method_investments,
                      "diluted_shares_weighted": sh, "shares_cover_page": cover},
           "sensitivity": sens, "market_price": price,
           "convention": "end-of-year cash flows from the valuation date; FCFF = EBIT(1-t) + D&A - capex - change in operating NWC; "
                         "terminal FCFF = NOPAT x (1+g) x (1 - g / RONIC)",
           "notes": []}
    # What the market price implies (reverse DCF): the uniform shift in the base-case EBIT margin that reproduces the
    # price. This describes the price; it is never used to set the assumptions.
    base_d = drivers_for(assumptions, "base")

    def base_value(shift: float) -> float:
        dr = [YearDrivers(x.revenue_growth, x.ebit_margin + shift, x.tax_rate, x.da_pct_revenue, x.capex_pct_revenue,
                          x.nwc_pct_revenue) for x in base_d]
        rows = project_fcff(base_rev, nwc0, dr)
        return bridge.per_share(enterprise_value([r["fcff"] for r in rows], w, g, rows[-1]["nopat"], ronic)["ev"])

    lo, hi = -0.5, 0.5
    if base_value(lo) < price < base_value(hi):
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if base_value(mid) < price else (lo, mid)
        out["market_implied"] = {"ebit_margin_shift": mid, "year5_ebit_margin": base_d[-1].ebit_margin + mid,
                                 "base_year5_ebit_margin": base_d[-1].ebit_margin,
                                 "note": "uniform change in the base-case EBIT margin that reproduces the market price"}
    else:
        out["market_implied"] = {"note": "no margin within +/-50 points reproduces the market price"}
    ts = cases["base"]["terminal_share"]
    if ts > 0.75:
        out["notes"].append(f"terminal value is {ts:.0%} of base-case enterprise value: disclose")

    if peers and peers.get("approved") and peers.get("selected"):
        pm = peer_multiples(peers["selected"])
        ebitda = ((facts["ttm"].get("ebit") or {}).get("value") or 0) + ((facts["ttm"].get("da") or {}).get("value") or 0)
        ni = (facts["ttm"].get("net_income") or {}).get("value") or 0
        adj = bridge.net_debt() + bridge.noncontrolling_interests - bridge.equity_method_investments
        try:
            out["comparables"] = {**pm, "target_ebitda": ebitda, "target_net_income": ni,
                                  "implied_per_share": implied_value_per_share(pm, ebitda, ni, adj, sh),
                                  "peer_data": "Yahoo Finance via yfinance (current, not as of the valuation date)"}
        except ValuationError as e:
            out["comparables"] = {"blocked": str(e)}
    else:
        out["comparables"] = {"blocked": "peer list not approved"}
    return out


def assumptions_tax(assumptions: dict) -> float:
    ts = [i["value"] for i in assumptions["items"] if i["scenario"] == "base" and i["driver"] == "tax_rate" and i["year"] == 5]
    return ts[0]


def tests_pass() -> tuple[bool, str]:
    """Step 6 runs only if the valuation tests pass (settings.yaml limits: value: tests must pass)."""
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_valuation.py", "tests/test_checks_value.py"],
                       cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else ""


def main(ticker: str, as_of: str) -> None:
    d = run.run_dir(ticker, as_of)
    ok, summary = tests_pass()
    if not ok:
        run.block(d, f"valuation tests fail ({summary}): fix the code, then unblock and rerun step 6 only")
        raise SystemExit(f"blocked: valuation tests fail: {summary}")
    rd = lambda n: json.loads((d / n).read_text())
    c = rd("checks.json")
    if c["blocks"]:
        run.block(d, f"{c['blocks']} blocking check(s): see checks.json")
        raise SystemExit("blocked: checks.json has blocking items")
    a = rd("assumptions.json")
    if a.get("status") != "approved":
        raise SystemExit("assumptions were not approved at the gate")
    settings = yaml.safe_load((ROOT / "settings.yaml").read_text())
    peers = rd("peers.json") if (d / "peers.json").exists() else None
    res = compute(rd("facts.json"), rd("history.json"), rd("evidence.json"), a, peers, settings)
    blob = b"".join((d / n).read_bytes() for n in ("facts.json", "assumptions.json", "evidence.json"))
    res["inputs_hash"] = hashlib.sha256(blob).hexdigest()
    try:
        res["code_version"] = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        res["code_version"] = "unknown"
    (d / "valuation.json").write_text(json.dumps(res, indent=2))
    run.log(d, event="value", base_per_share=round(res["cases"]["base"]["per_share"], 2), inputs_hash=res["inputs_hash"][:12],
            code_version=res["code_version"])
    print(f"saved {d / 'valuation.json'}; base per share {res['cases']['base']['per_share']:.2f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
