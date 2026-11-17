"""Step 5, review (the Python part): deterministic checks on the facts and the proposed assumptions.

Usage: python -m pipeline.checks <TICKER> <DATE> [--verdicts review-verdicts.json]

Severity follows the materiality rule in settings.yaml: `block` when an issue could move value per share by more than
5% or by an unknown amount; `warn` for 1-5% (stated in the report); `pass` otherwise.
The reviewer subagent returns verdicts (supported | contradicted | unsupported); they are validated and merged here.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from . import run

DRIVERS = ["revenue_growth", "ebit_margin", "tax_rate", "da_pct_revenue", "capex_pct_revenue", "nwc_pct_revenue"]
SCENARIOS = ["base", "bear", "bull"]
YEARS = [1, 2, 3, 4, 5]
BOUNDS = {"revenue_growth": (-0.30, 0.40), "ebit_margin": (-0.10, 0.60), "tax_rate": (0.0, 0.40),
          "da_pct_revenue": (0.0, 0.30), "capex_pct_revenue": (0.0, 0.30), "nwc_pct_revenue": (-0.30, 0.50)}
VERDICTS = {"supported", "contradicted", "unsupported"}


def evidence_ids(facts: dict, history: dict) -> set[str]:
    ids = set()
    for v in facts["annual"].values():
        ids |= {x["id"] for x in v}
    ids |= {x["id"] for x in facts["ttm"].values()}
    ids |= {x["id"] for x in facts["balance"].values()}
    for k in ("shares_outstanding", "diluted_shares"):
        if k in facts:
            ids.add(facts[k]["id"])
    ids |= {f"flag:{f['item']}:{f['to']}" for f in history["flags"]}
    return ids


def check(facts: dict, history: dict, evidence: dict, assumptions: dict, settings: dict, today: str) -> list[dict]:
    out: list[dict] = []
    add = lambda target, severity, note, verdict="n/a", pointer="check": out.append(
        {"target": target, "verdict": verdict, "pointer": pointer, "severity": severity, "note": note})

    # inputs that the bridge and the discount rate cannot do without
    if "diluted_shares" not in facts:
        add("diluted_shares", "block", "diluted share count missing: value per share unknown", pointer="check:shares")
    rf = (evidence.get("risk_free") or {}).get("value")
    if rf is None:
        add("risk_free", "block", "no risk-free rate (set FRED_API_KEY or risk_free_rate_manual)", pointer="check:rf")
    elif (evidence["risk_free"].get("warning")):
        add("risk_free", "warn", evidence["risk_free"]["warning"], pointer="check:rf")
    if (evidence.get("market") or {}).get("beta") is None:
        add("beta", "block", "no beta from Yahoo", pointer="check:beta")
    for w in facts.get("warnings", []):
        add("facts", "warn", w, pointer="check:stale-tag")
    for m in facts.get("missing", []):
        add(m["id"], "block" if m.get("blocks") else "warn", m["reason"], pointer="check:missing")
    if not facts["ttm"].get("revenue"):
        add("ttm_revenue", "warn", "no trailing-twelve-month revenue: the last annual figure is used", pointer="check:ttm")
    if facts["balance"].get("cash", {}).get("as_of"):
        age = (date.fromisoformat(today) - date.fromisoformat(facts["balance"]["cash"]["as_of"])).days
        if age > 200:
            add("balance_sheet", "block", f"latest balance sheet is {age} days old", pointer="check:stale-filing")

    # assumptions: structure, evidence, bounds, ordering
    items = assumptions.get("items", [])
    ids = evidence_ids(facts, history)
    have = {(i["scenario"], i["year"], i["driver"]): i for i in items}
    for s in SCENARIOS:
        for y in YEARS:
            for dr in DRIVERS:
                if (s, y, dr) not in have:
                    add(f"{s}:{y}:{dr}", "block", "assumption missing", pointer="check:complete")
    for i in items:
        t = i["id"]
        lo, hi = BOUNDS.get(i["driver"], (None, None))
        if lo is not None and not (lo <= i["value"] <= hi):
            add(t, "block", f"{i['driver']}={i['value']} is outside the sanity bounds [{lo}, {hi}]", pointer="check:bounds")
        bad = [e for e in i.get("evidence", []) if e not in ids]
        if bad:
            add(t, "block", f"evidence ids that do not exist: {bad}", pointer="check:evidence-ids")
        if not i.get("evidence") and not i.get("judgment"):
            add(t, "block", "no evidence and no judgment label", pointer="check:evidence")
    for y in YEARS:
        for dr in ("revenue_growth", "ebit_margin"):
            v = {s: have.get((s, y, dr), {}).get("value") for s in SCENARIOS}
            if None not in v.values() and not (v["bear"] <= v["base"] <= v["bull"]):
                add(f"{y}:{dr}", "warn", f"cases not ordered bear <= base <= bull ({v})", pointer="check:ordering")
    g = (assumptions.get("terminal_growth") or {}).get("value")
    cap = min(x for x in (rf, 0.04) if x is not None)
    if g is None:
        add("terminal_growth", "block", "terminal growth missing", pointer="check:terminal")
    elif g > cap:
        add("terminal_growth", "block", f"terminal growth {g} is above the cap {cap} (risk-free rate or 4%)",
            pointer="check:terminal")
    if not out:
        add("all", "pass", "all deterministic checks passed")
    return out


def merge_reviewer(checks: list[dict], verdicts: list[dict], assumptions: dict) -> list[dict]:
    """Validate and add the reviewer subagent's verdicts. Contradicted -> block; unsupported -> warn if the
    assumption carries a judgment label, otherwise block. A target without a verdict is itself a block."""
    known = {i["id"] for i in assumptions.get("items", [])}
    seen = set()
    for v in verdicts:
        if v.get("verdict") not in VERDICTS or v.get("target") not in known or not v.get("pointer"):
            checks.append({"target": v.get("target", "?"), "verdict": "invalid", "pointer": "check:verdict-format",
                           "severity": "block", "note": "reviewer verdict malformed or points at an unknown assumption"})
            continue
        seen.add(v["target"])
        sev = {"supported": "pass", "contradicted": "block", "unsupported": "warn"}[v["verdict"]]
        checks.append({**v, "severity": sev})
    for k in sorted(known - seen):
        checks.append({"target": k, "verdict": "none", "pointer": "check:review", "severity": "block",
                       "note": "the reviewer gave no verdict for this assumption"})
    return checks


def main(ticker: str, as_of: str, verdicts_file: str | None = None) -> None:
    import yaml
    from pathlib import Path
    d = run.run_dir(ticker, as_of)
    rd = lambda n: json.loads((d / n).read_text())
    settings = yaml.safe_load((Path(__file__).resolve().parent.parent / "settings.yaml").read_text())
    assumptions = rd("assumptions.json")
    checks = check(rd("facts.json"), rd("history.json"), rd("evidence.json"), assumptions, settings, as_of)
    if verdicts_file:
        checks = merge_reviewer(checks, json.loads((d / verdicts_file).read_text()), assumptions)
    res = {"checks": checks, "blocks": sum(c["severity"] == "block" for c in checks),
           "warns": sum(c["severity"] == "warn" for c in checks), "reviewer_merged": bool(verdicts_file)}
    (d / "checks.json").write_text(json.dumps(res, indent=2))
    run.log(d, event="checks", blocks=res["blocks"], warns=res["warns"])
    print(f"saved {d / 'checks.json'}: {res['blocks']} block, {res['warns']} warn")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[a.index("--verdicts") + 1] if "--verdicts" in a else None)
