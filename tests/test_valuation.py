"""Hand-checked cases: every expected value below was worked out on paper, not produced by the code."""
import math

import pytest

from valuation.bridge import Bridge
from valuation.comps import implied_value_per_share, peer_multiples
from valuation.dcf import (ValuationError, YearDrivers, capm, enterprise_value, project_fcff,
                           sensitivity_wacc_g, terminal_value, wacc)


def test_capm():
    assert capm(0.04, 1.2, 0.05) == pytest.approx(0.10)


def test_wacc_weights_and_tax_shield():
    # .6*.10 + .4*.05*(1-.2) = .06 + .016
    assert wacc(60, 40, 0.10, 0.05, 0.20) == pytest.approx(0.076)


def test_wacc_rejects_bad_weights():
    with pytest.raises(ValuationError):
        wacc(0, 40, 0.1, 0.05, 0.2)


def test_flat_perpetuity_is_cash_flow_over_rate():
    # 100 a year forever at 10% is worth 1000: explicit part 173.554 plus terminal part 826.446
    r = enterprise_value([100, 100], 0.10, 0.0)
    assert r["pv_explicit"] == pytest.approx(173.5537, abs=1e-3)
    assert r["pv_terminal"] == pytest.approx(826.4463, abs=1e-3)
    assert r["ev"] == pytest.approx(1000.0)
    assert r["ev"] == pytest.approx(r["pv_explicit"] + r["pv_terminal"])


def test_wacc_must_exceed_g():
    with pytest.raises(ValuationError):
        terminal_value(100, 0.03, 0.03)


def test_project_fcff_one_year():
    d = YearDrivers(0.10, 0.20, 0.25, 0.03, 0.05, 0.10)
    row = project_fcff(1000, 100, [d])[0]
    # revenue 1100, EBIT 220, NOPAT 165, D&A 33, capex 55, NWC 110 -> change 10; FCFF = 165+33-55-10
    assert row["revenue"] == pytest.approx(1100)
    assert row["fcff"] == pytest.approx(133)


def test_bridge_includes_all_claims():
    b = Bridge(debt=200, cash=50, noncontrolling_interests=30, preferred=20, equity_method_investments=40,
               as_of="2026-09-30", diluted_shares=80)
    assert b.equity_value(1000) == pytest.approx(840)
    assert b.per_share(1000) == pytest.approx(10.5)


def test_missing_share_count_blocks():
    with pytest.raises(ValuationError):
        Bridge(debt=0, cash=0).per_share(1000)


def test_comps_exclude_and_disclose_negative_earnings():
    peers = [{"ticker": "A", "market_cap": 1000, "net_debt": 200, "ebitda": 120, "net_income": 60},
             {"ticker": "B", "market_cap": 500, "net_debt": 0, "ebitda": 50, "net_income": -10}]
    m = peer_multiples(peers)
    assert m["median"]["ev_ebitda"] == pytest.approx(10.0)
    assert m["median"]["pe"] == pytest.approx(1000 / 60)
    assert m["excluded"] == [{"ticker": "B", "multiple": "pe", "reason": "non-positive or missing denominator"}]
    imp = implied_value_per_share(m, ebitda=100, net_income=40, net_debt_adj=100, diluted_shares=50)
    assert imp["ev_ebitda"] == pytest.approx(18.0)
    assert imp["pe"] == pytest.approx(1000 / 60 * 40 / 50)


def test_sensitivity_grid_blanks_invalid_cells_and_centre_matches():
    b = Bridge(debt=0, cash=0, diluted_shares=1)
    grid = sensitivity_wacc_g([100, 100], [0.03, 0.10], [0.0, 0.03], b.per_share)
    assert grid[0][1] is None                      # WACC 3% <= g 3%
    assert grid[1][0] == pytest.approx(1000.0)     # WACC 10%, g 0 equals the hand-checked case
    assert not any(isinstance(c, float) and math.isnan(c) for row in grid for c in row)
