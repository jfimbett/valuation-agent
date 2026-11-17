"""Clean numbers from SEC company facts (XBRL). Pure functions: no network, easy to test.

Rules: only facts filed on or before the valuation date (no look-ahead); a period is a duration of about a year
(350-380 days) or a quarter (80-100 days); year-to-date values are converted to quarters (Q2 = 6M - Q1, Q3 = 9M - 6M,
Q4 = FY - 9M); the latest filing wins when a period was restated; units: USD -> USD millions, shares -> millions.
A value that cannot be found stays missing; it is never turned into 0.
"""
from __future__ import annotations

from datetime import date

FORMS = {"10-K", "10-K/A", "10-KT", "10-Q", "10-Q/A"}

TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "ebit": ["OperatingIncomeLoss"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
}
INSTANT_TAGS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "short_term_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "MarketableSecurities"],
    "debt_long": ["LongTermDebtAndCapitalLeaseObligations", "LongTermDebtNoncurrent", "LongTermDebt"],
    "debt_short": ["LongTermDebtAndCapitalLeaseObligationsCurrent", "LongTermDebtCurrent", "DebtCurrent"],
    "short_term_borrowings": ["OtherShortTermBorrowings", "ShortTermBorrowings", "CommercialPaper"],
    "noncontrolling_interests": ["MinorityInterest"],
    "equity_method_investments": ["EquityMethodInvestments"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
}


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _days(i: dict) -> int:
    return (_d(i["end"]) - _d(i["start"])).days


def _scale(unit: str) -> float:
    return 1e6 if unit in ("USD", "shares") else 1.0


def raw_items(companyfacts: dict, tag: str, as_of: str, taxonomy: str = "us-gaap") -> list[dict]:
    node = companyfacts.get("facts", {}).get(taxonomy, {}).get(tag)
    if not node:
        return []
    out = []
    for unit, rows in node["units"].items():
        for r in rows:
            if r.get("filed", "9999") > as_of:  # look-ahead filter
                continue
            if r.get("form") not in FORMS:      # proxy statements and others repeat values; only 10-K/10-Q count
                continue
            out.append({"tag": f"{taxonomy}:{tag}", "unit": unit, "value": r["val"] / _scale(unit),
                        "start": r.get("start"), "end": r["end"], "form": r.get("form"), "fp": r.get("fp"),
                        "filed": r["filed"], "accession": r.get("accn")})
    return out


def _latest_per_period(items: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for it in items:
        k = (it["start"], it["end"])
        if k not in best or it["filed"] > best[k]["filed"]:
            best[k] = it
    return list(best.values())


def _freshest(candidates: list[list[dict]], key: str = "end") -> list[dict]:
    """Of the tags that have data, use the one with the newest period (a company may stop using an old tag).
    Ties go to the tag listed first."""
    candidates = [c for c in candidates if c]
    return max(candidates, key=lambda c: max(i[key] for i in c)) if candidates else []


def annual(companyfacts: dict, tags: list[str], as_of: str) -> list[dict]:
    """Fiscal-year values from the tag with the newest data, newest first."""
    per_tag = []
    for tag in tags:
        items = [i for i in raw_items(companyfacts, tag, as_of)
                 if i["start"] and 350 <= _days(i) <= 380 and i["form"] in ("10-K", "10-K/A")]
        per_tag.append(sorted(_latest_per_period(items), key=lambda i: i["end"], reverse=True))
    best = _freshest(per_tag)
    return best


def quarters(companyfacts: dict, tags: list[str], as_of: str) -> list[dict]:
    """Single-quarter values, converting year-to-date figures. Newest first; kind is 'reported' or 'derived'."""
    per_tag = []
    for tag in tags:
        items = [i for i in raw_items(companyfacts, tag, as_of) if i["start"]]
        if not items:
            continue
        by = _latest_per_period(items)
        qs: dict[str, dict] = {i["end"]: {**i, "kind": "reported"}
                               for i in by if 80 <= _days(i) <= 100 and i["form"] == "10-Q"}
        for i in by:
            if i["form"] not in ("10-Q", "10-K", "10-K/A"):
                continue
            n = _days(i)
            if 170 <= n <= 195:
                prior = (80, 100)            # 6M - Q1
            elif 260 <= n <= 285:
                prior = (170, 195)           # 9M - 6M
            elif 350 <= n <= 380:
                prior = (260, 285)           # FY - 9M
            else:
                continue
            for p in by:
                if p["start"] == i["start"] and prior[0] <= _days(p) <= prior[1] and p["end"] < i["end"]:
                    qs.setdefault(i["end"], {**i, "kind": "derived", "start": p["end"],
                                             "value": i["value"] - p["value"],
                                             "derived_from": [i["accession"], p["accession"]]})
        for i in by:   # Q4 = FY - (Q1 + Q2 + Q3) when the filings give three single quarters but no nine-month total
            if i["form"] in ("10-K", "10-K/A") and 350 <= _days(i) <= 380 and i["end"] not in qs:
                inside = [q for q in qs.values() if q["start"] >= i["start"] and q["end"] < i["end"] and _days(q) <= 100]
                if len(inside) == 3:
                    qs[i["end"]] = {**i, "kind": "derived", "start": max(q["end"] for q in inside),
                                    "value": i["value"] - sum(q["value"] for q in inside),
                                    "derived_from": [i["accession"]] + [q["accession"] for q in inside]}
        if qs:
            per_tag.append(sorted(qs.values(), key=lambda q: q["end"], reverse=True))
    return _freshest(per_tag)


def ttm(qs: list[dict]) -> dict | None:
    """Sum of the latest four consecutive single quarters, or None (missing, never 0)."""
    if len(qs) < 4:
        return None
    last4 = qs[:4]
    if not all(70 <= (_d(a["end"]) - _d(b["end"])).days <= 110 for a, b in zip(last4, last4[1:])):
        return None
    return {"value": sum(q["value"] for q in last4), "end": last4[0]["end"], "quarters": [q["end"] for q in last4]}


def latest_instant(companyfacts: dict, tags: list[str], as_of: str, taxonomy: str = "us-gaap",
                   not_before: str | None = None) -> dict | None:
    """Most recent point-in-time value (balance sheet, share count) filed on or before as_of.
    Values dated before not_before are stale (a company stopped using that tag): treated as missing."""
    for tag in tags:
        items = [i for i in raw_items(companyfacts, tag, as_of, taxonomy) if not i["start"]
                 and (not_before is None or i["end"] >= not_before)]
        if items:
            return max(items, key=lambda i: (i["end"], i["filed"]))
    return None


def latest_weighted(companyfacts: dict, tags: list[str], as_of: str) -> dict | None:
    """Latest reported weighted-average value (e.g. diluted shares). Averages are never added or subtracted."""
    for tag in tags:
        items = [i for i in raw_items(companyfacts, tag, as_of)
                 if i["start"] and (80 <= _days(i) <= 100 or 350 <= _days(i) <= 380)]
        if items:
            quarterly = [i for i in items if _days(i) <= 100]
            pool = quarterly or items
            return max(pool, key=lambda i: (i["end"], i["filed"]))
    return None
