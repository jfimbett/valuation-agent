"""Step 2, read the numbers (the Python part): XBRL facts to facts.json, each with unit, period and source.

Usage: python -m pipeline.read <TICKER> <DATE>
Numbers that exist only in filing text are left to the `reader` subagent; here they are listed under `missing`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import facts, run

ROOT = Path(__file__).resolve().parent.parent
MAX_AGE_DAYS = 120   # a balance-sheet tag older than this, relative to the newest balance sheet, is stale


def _prov(it: dict, cik: str) -> dict:
    return {"cik": cik, "form": it["form"], "accession": it["accession"], "filed": it["filed"],
            "xbrl_tag": it["tag"], "url": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"}


def main(ticker: str, as_of: str) -> None:
    d = run.run_dir(ticker, as_of)
    ev = json.loads((d / "evidence.json").read_text())
    cik = ev["cik"]
    cf = json.loads((ROOT / "evidence" / cik / "companyfacts.json").read_text())
    out: dict = {"ticker": ev["ticker"], "valuation_date": as_of, "unit": "USD_m", "annual": {}, "ttm": {},
                 "balance": {}, "missing": [], "warnings": []}

    for name, tags in facts.TAGS.items():
        ann = facts.annual(cf, tags, as_of)
        if not ann:
            out["missing"].append({"id": name, "reason": "no annual value found in XBRL", "blocks": []})
            continue
        out["annual"][name] = [{"id": f"{name}_{a['end']}", "kind": "reported", "value": a["value"],
                                "period": {"start": a["start"], "end": a["end"]}, "source": _prov(a, cik)}
                               for a in ann[:6]]
        t = facts.ttm(facts.quarters(cf, tags, as_of))
        if t:
            out["ttm"][name] = {"id": f"{name}_ttm", "kind": "calculated", "value": t["value"], "unit": "USD_m",
                                "formula": "sum of the last four single quarters (year-to-date converted)",
                                "quarters": t["quarters"], "end": t["end"]}

    ref = None
    cash = facts.latest_instant(cf, facts.INSTANT_TAGS["cash"], as_of)
    if cash:
        ref = cash["end"]
    if ref is None:
        out["missing"].append({"id": "balance_sheet", "reason": "no cash value found", "blocks": ["bridge"]})
    else:
        from datetime import date, timedelta
        floor = (date.fromisoformat(ref) - timedelta(days=MAX_AGE_DAYS)).isoformat()
        for name, tags in facts.INSTANT_TAGS.items():
            it = facts.latest_instant(cf, tags, as_of, not_before=floor)
            if it:
                out["balance"][name] = {"id": f"{name}_{it['end']}", "kind": "reported", "value": it["value"],
                                        "as_of": it["end"], "source": _prov(it, cik)}
            else:
                out["balance"][name] = {"id": f"{name}_missing", "kind": "missing", "value": None,
                                        "reason": f"no value dated on or after {floor} (tag not used recently)"}
                out["warnings"].append(f"{name}: not reported near {ref}; treated as missing, not 0. "
                                       f"Check whether it matters (materiality rule).")
        out["balance_date"] = ref

    sh = facts.latest_instant(cf, ["EntityCommonStockSharesOutstanding"], as_of, taxonomy="dei")
    if sh:
        out["shares_outstanding"] = {"id": "shares_cover", "kind": "reported", "value": sh["value"], "unit": "shares_m",
                                     "as_of": sh["end"], "source": _prov(sh, cik)}
    else:
        out["missing"].append({"id": "shares_cover", "reason": "no cover-page share count filed before the date",
                               "blocks": ["value per share"]})
    dil = facts.latest_weighted(cf, ["WeightedAverageNumberOfDilutedSharesOutstanding"], as_of)
    if dil:
        out["diluted_shares"] = {"id": "shares_diluted_weighted", "kind": "reported", "value": dil["value"],
                                 "unit": "shares_m", "period": {"start": dil["start"], "end": dil["end"]},
                                 "source": _prov(dil, cik)}
    else:
        out["missing"].append({"id": "shares_diluted_weighted", "reason": "not found", "blocks": ["value per share"]})

    # Staleness of the filing set: the newest filing used must be recent enough.
    newest = max([x["source"]["filed"] for v in out["annual"].values() for x in v] or ["0000-00-00"])
    out["latest_annual_filed"] = newest
    (d / "facts.json").write_text(json.dumps(out, indent=2))
    run.log(d, event="read", annual_items=sum(len(v) for v in out["annual"].values()),
            missing=[m["id"] for m in out["missing"]], warnings=len(out["warnings"]))
    print(f"saved {d / 'facts.json'}; missing: {[m['id'] for m in out['missing']]}; warnings: {len(out['warnings'])}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
