"""Firm-route DCF (FCFF discounted at WACC). All money in USD millions; rates as decimals.

Convention: end-of-year cash flows, t = 1..N from the valuation date (a simplification, stated in every report).
"""
from __future__ import annotations

from dataclasses import dataclass


class ValuationError(ValueError):
    """Raised when inputs are inconsistent. The pipeline turns this into a block, never a silent default."""


def capm(rf: float, beta: float, erp: float) -> float:
    """Cost of equity = risk-free + beta * equity risk premium."""
    return rf + beta * erp


def wacc(equity_value: float, debt_value: float, cost_equity: float, cost_debt: float, tax_rate: float) -> float:
    if equity_value <= 0 or debt_value < 0:
        raise ValuationError("equity value must be positive and debt non-negative for WACC weights")
    v = equity_value + debt_value
    return equity_value / v * cost_equity + debt_value / v * cost_debt * (1 - tax_rate)


@dataclass(frozen=True)
class YearDrivers:
    revenue_growth: float
    ebit_margin: float
    tax_rate: float
    da_pct_revenue: float
    capex_pct_revenue: float
    nwc_pct_revenue: float  # net working capital as a share of revenue


def project_fcff(base_revenue: float, base_nwc: float, drivers: list[YearDrivers]) -> list[dict]:
    """Turn drivers into projected FCFF. FCFF = EBIT(1-t) + D&A - capex - change in NWC."""
    if base_revenue <= 0:
        raise ValuationError("base revenue must be positive")
    rows, revenue, nwc = [], base_revenue, base_nwc
    for i, d in enumerate(drivers, start=1):
        revenue = revenue * (1 + d.revenue_growth)
        ebit = revenue * d.ebit_margin
        nopat = ebit * (1 - d.tax_rate)
        da, capex = revenue * d.da_pct_revenue, revenue * d.capex_pct_revenue
        new_nwc = revenue * d.nwc_pct_revenue
        d_nwc, nwc = new_nwc - nwc, new_nwc
        rows.append({"year": i, "revenue": revenue, "ebit": ebit, "nopat": nopat, "da": da, "capex": capex,
                     "delta_nwc": d_nwc, "fcff": nopat + da - capex - d_nwc})
    return rows


def terminal_value(last_fcff: float, discount_rate: float, g: float, nopat_last: float | None = None,
                   ronic: float | None = None) -> float:
    """Gordon growth. Without nopat_last: FCFF_N x (1+g) / (r - g).
    With nopat_last (normalised terminal year): FCFF_{N+1} = NOPAT_N x (1+g) x (1 - g / RONIC), where RONIC is the
    return on new capital (default: r, so growth adds no value). Year-5 capex above D&A is not carried forever."""
    if discount_rate <= g:
        raise ValuationError(f"WACC ({discount_rate:.4f}) must exceed terminal growth ({g:.4f})")
    if nopat_last is None:
        return last_fcff * (1 + g) / (discount_rate - g)
    ronic = discount_rate if ronic is None else ronic
    if ronic <= g:
        raise ValuationError(f"return on new capital ({ronic:.4f}) must exceed terminal growth ({g:.4f})")
    return nopat_last * (1 + g) * (1 - g / ronic) / (discount_rate - g)


def enterprise_value(fcffs: list[float], discount_rate: float, g: float, nopat_last: float | None = None,
                     ronic: float | None = None) -> dict:
    """EV = PV(explicit FCFF) + PV(terminal value). Returns the parts so tests and reports can check them."""
    n = len(fcffs)
    if n == 0:
        raise ValuationError("no cash flows")
    pv_explicit = sum(cf / (1 + discount_rate) ** t for t, cf in enumerate(fcffs, start=1))
    tv = terminal_value(fcffs[-1], discount_rate, g, nopat_last, ronic)
    pv_terminal = tv / (1 + discount_rate) ** n
    ev = pv_explicit + pv_terminal
    return {"pv_explicit": pv_explicit, "terminal_value": tv, "pv_terminal": pv_terminal, "ev": ev,
            "terminal_share": pv_terminal / ev if ev else float("nan")}


def sensitivity_wacc_g(fcffs: list[float], waccs: list[float], gs: list[float], bridge_fn,
                       nopat_last: float | None = None, ronic: float | None = None) -> list[list[float | None]]:
    """Value per share on a WACC x g grid. Cells where WACC <= g are None (shown as 'n/a', never forced)."""
    grid = []
    for w in waccs:
        row = []
        for g in gs:
            row.append(None if w <= g else bridge_fn(enterprise_value(fcffs, w, g, nopat_last, ronic)["ev"]))
        grid.append(row)
    return grid
