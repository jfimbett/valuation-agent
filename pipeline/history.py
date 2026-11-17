"""Step 3, history (the Python part): growth, margins, unusual jumps. The subagent may add a short comment that cites
only values found here. Usage: python -m pipeline.history <TICKER> <DATE>"""
from __future__ import annotations

import json
import sys

from . import run

JUMP = 0.25   # flag a year-on-year change bigger than 25% in a line item


def _series(facts: dict, name: str) -> dict[str, float]:
    return {x["period"]["end"]: x["value"] for x in facts["annual"].get(name, [])}


def build(facts: dict) -> dict:
    rev, ebit, da, capex = (_series(facts, k) for k in ("revenue", "ebit", "da", "capex"))
    tax, pre = _series(facts, "income_tax"), _series(facts, "pretax_income")
    years = sorted(rev)
    rows, flags = [], []
    for i, y in enumerate(years):
        row = {"year_end": y, "revenue": rev[y]}
        if y in ebit:
            row["ebit_margin"] = ebit[y] / rev[y]
        if y in da:
            row["da_pct_revenue"] = da[y] / rev[y]
        if y in capex:
            row["capex_pct_revenue"] = capex[y] / rev[y]
        if y in tax and y in pre and pre[y] > 0:
            row["tax_rate"] = tax[y] / pre[y]
        if i:
            row["revenue_growth"] = rev[y] / rev[years[i - 1]] - 1
        rows.append(row)
    for name in ("revenue", "ebit", "capex", "da", "income_tax"):
        s = _series(facts, name)
        ys = sorted(s)
        for a, b in zip(ys, ys[1:]):
            if s[a] and abs(s[b] / s[a] - 1) > JUMP:
                flags.append({"item": name, "from": a, "to": b, "change": s[b] / s[a] - 1,
                              "note": "unusual jump: look for a cause before using this year in the forecast"})
    out = {"unit": "USD_m", "rows": rows, "flags": flags, "comment": None}
    nwc = operating_nwc(facts)
    if nwc is not None and facts.get("ttm", {}).get("revenue"):
        out["operating_nwc"] = {"value": nwc, "as_of": facts.get("balance_date"),
                                "pct_of_ttm_revenue": nwc / facts["ttm"]["revenue"]["value"],
                                "definition": "(current assets - cash - short-term investments) - (current liabilities - short-term debt)"}
    return out


def operating_nwc(facts: dict) -> float | None:
    b = facts.get("balance", {})
    v = lambda k: (b.get(k) or {}).get("value") or 0.0
    if not b.get("current_assets", {}).get("value") or not b.get("current_liabilities", {}).get("value"):
        return None
    return (v("current_assets") - v("cash") - v("short_term_investments")) -            (v("current_liabilities") - v("debt_short") - v("short_term_borrowings"))


def main(ticker: str, as_of: str) -> None:
    d = run.run_dir(ticker, as_of)
    facts = json.loads((d / "facts.json").read_text())
    h = build(facts)
    (d / "history.json").write_text(json.dumps(h, indent=2))
    run.log(d, event="history", years=len(h["rows"]), flags=len(h["flags"]))
    print(f"saved {d / 'history.json'}; {len(h['flags'])} unusual jump(s)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
