"""SYNTHETIC fixture: Synthetic Beverage Co. All numbers are invented for tests."""


def facts():
    def ann(name, vals):
        return [{"id": f"{name}_{y}", "kind": "reported", "value": v,
                 "period": {"start": f"{y}-01-01", "end": f"{y}-12-31"},
                 "source": {"form": "10-K", "filed": f"{y + 1}-02-20"}} for y, v in vals]

    def inst(k, v):
        return {"id": f"{k}_2026-09-30", "kind": "reported", "value": v, "as_of": "2026-09-30"}

    bal = dict(cash=100.0, short_term_investments=0.0, debt_long=300.0, debt_short=50.0, short_term_borrowings=0.0,
               noncontrolling_interests=10.0, equity_method_investments=40.0, current_assets=400.0,
               current_liabilities=250.0)
    return {"ticker": "SYN", "valuation_date": "2026-11-17", "unit": "USD_m", "balance_date": "2026-09-30",
            "annual": {"revenue": ann("revenue", [(2025, 1000.0), (2024, 950.0)]),
                       "interest_expense": ann("interest_expense", [(2025, 20.0)])},
            "ttm": {"revenue": {"id": "revenue_ttm", "value": 1000.0}, "ebit": {"id": "ebit_ttm", "value": 200.0},
                    "da": {"id": "da_ttm", "value": 30.0}, "net_income": {"id": "net_income_ttm", "value": 140.0},
                    "interest_expense": {"id": "interest_expense_ttm", "value": 20.0}},
            "balance": {k: inst(k, v) for k, v in bal.items()},
            "shares_outstanding": {"id": "shares_cover", "value": 100.0},
            "diluted_shares": {"id": "shares_diluted_weighted", "value": 102.0},
            "missing": [], "warnings": []}


def history():
    return {"rows": [], "flags": []}


def evidence():
    return {"risk_free": {"value": 0.04}, "market": {"beta": 1.0, "price": 20.0}}


def assumptions(g=0.025):
    base = dict(revenue_growth=0.05, ebit_margin=0.20, tax_rate=0.20, da_pct_revenue=0.03, capex_pct_revenue=0.04,
                nwc_pct_revenue=0.15)
    shift = {"bear": dict(revenue_growth=-0.03, ebit_margin=-0.03), "base": {},
             "bull": dict(revenue_growth=0.03, ebit_margin=0.03)}
    items = []
    for s, sh in shift.items():
        for y in range(1, 6):
            for dr, v in base.items():
                items.append({"id": f"{dr}_y{y}_{s}", "scenario": s, "year": y, "driver": dr,
                              "value": v + sh.get(dr, 0), "evidence": ["revenue_2025"], "judgment": None})
    return {"status": "approved", "items": items,
            "terminal_growth": {"value": g, "evidence": [], "judgment": "synthetic"}}
