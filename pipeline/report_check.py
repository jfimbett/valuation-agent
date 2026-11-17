"""Step 7 check: every number in report.md must trace to a saved artifact, and every warning must appear.

Usage: python -m pipeline.report_check <TICKER> <DATE>   (exit 1 and block on any mismatch)
A number matches if an artifact value, rounded to the number's own decimals, equals it; percentages (x100) and
billions (/1000) are accepted. Years and dates are ignored. The report writer may not change a number.
"""
from __future__ import annotations

import json
import re
import sys

from . import run

NUM = re.compile(r"(?<![\w.])-?\$?\d[\d,]*\.?\d*%?")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def flatten(x, out: list[float]) -> None:
    if isinstance(x, bool):
        return
    if isinstance(x, (int, float)):
        out.append(float(x))
    elif isinstance(x, dict):
        for v in x.values():
            flatten(v, out)
    elif isinstance(x, list):
        for v in x:
            flatten(v, out)


def numbers_in(text: str) -> list[str]:
    text = DATE.sub(" ", text)
    text = re.sub(r"`[^`]*`", " ", text)          # ids in backticks are labels, not figures
    return [m.group(0) for m in NUM.finditer(text)]


def matches(token: str, pool: list[float]) -> bool:
    t = token.replace("$", "").replace(",", "")
    pct = t.endswith("%")
    t = t.rstrip("%")
    if not t or t in ("-",):
        return True
    try:
        val = float(t)
    except ValueError:
        return True
    if re.fullmatch(r"(19|20)\d\d", t.lstrip("-")) or val in (0.0,):
        return True
    dec = len(t.split(".")[1]) if "." in t else 0
    scales = [100.0] if pct else [1.0, 1e-3, 1e-6]
    return any(round(p * s, dec) == round(val, dec) or abs(p * s - val) <= 0.5 * 10 ** -dec + 1e-9
               for p in pool for s in scales)


def check_report(report: str, artifacts: list[dict], checks: dict) -> dict:
    pool: list[float] = []
    for a in artifacts:
        flatten(a, pool)
    unmatched = sorted({n for n in numbers_in(report) if not matches(n, pool)})
    missing_warnings = [c["target"] for c in checks["checks"]
                        if c["severity"] == "warn" and c["target"] not in report]
    return {"unmatched_numbers": unmatched, "warnings_missing_from_report": missing_warnings,
            "ok": not unmatched and not missing_warnings}


def main(ticker: str, as_of: str) -> None:
    d = run.run_dir(ticker, as_of)
    rd = lambda n: json.loads((d / n).read_text())
    res = check_report((d / "report.md").read_text(), [rd("valuation.json"), rd("facts.json"), rd("history.json"),
                                                       rd("evidence.json")], rd("checks.json"))
    (d / "report-check.json").write_text(json.dumps(res, indent=2))
    run.log(d, event="report_check", ok=res["ok"], unmatched=len(res["unmatched_numbers"]))
    print(json.dumps(res))
    if not res["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
