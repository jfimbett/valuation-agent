import pytest

from pipeline import checks as ck
from pipeline import value
from tests.make_synth import assumptions, evidence, facts, history

SETTINGS = {"discount_rate": {"equity_risk_premium": 0.05}}


def blocks(res):
    return [c for c in res if c["severity"] == "block"]


def run_checks(f=None, a=None, e=None):
    return ck.check(f or facts(), history(), e or evidence(), a or assumptions(), SETTINGS, "2026-11-17")


def test_clean_synthetic_case_passes():
    assert not blocks(run_checks())


def test_missing_share_count_blocks():
    f = facts()
    del f["diluted_shares"]
    assert any(c["target"] == "diluted_shares" for c in blocks(run_checks(f=f)))


def test_missing_risk_free_blocks():
    e = evidence()
    e["risk_free"] = {"value": None}
    assert any(c["target"] == "risk_free" for c in blocks(run_checks(e=e)))


def test_terminal_growth_above_cap_blocks():
    assert any(c["target"] == "terminal_growth" for c in blocks(run_checks(a=assumptions(g=0.05))))


def test_out_of_bounds_fake_and_missing_evidence_block():
    a = assumptions()
    a["items"][0]["value"] = 0.9
    a["items"][1]["evidence"] = ["made_up_id"]
    a["items"][2]["evidence"], a["items"][2]["judgment"] = [], None
    notes = " ".join(c["note"] for c in blocks(run_checks(a=a)))
    assert "outside the sanity bounds" in notes and "do not exist" in notes and "no evidence" in notes


def test_incomplete_assumptions_block():
    a = assumptions()
    a["items"] = a["items"][:-1]
    assert any("assumption missing" in c["note"] for c in blocks(run_checks(a=a)))


def test_reviewer_verdicts_are_validated():
    a = assumptions()
    ids = [i["id"] for i in a["items"]]
    merged = ck.merge_reviewer([], [{"target": ids[0], "verdict": "contradicted", "pointer": "revenue_2025", "note": "x"},
                                    {"target": ids[1], "verdict": "banana", "pointer": "p"}], a)
    sev = {c["target"]: c["severity"] for c in merged}
    assert sev[ids[0]] == "block" and sev[ids[2]] == "block"   # contradicted; no verdict at all
    assert any(c["verdict"] == "invalid" for c in merged)


def test_value_hand_check():
    r = value.compute(facts(), history(), evidence(), assumptions(), None, SETTINGS)
    base = r["cases"]["base"]
    # equity = EV - debt 350 + cash 100 - NCI 10 + equity-method 40; per share on 102m diluted shares
    assert base["ev"] == pytest.approx(base["pv_explicit"] + base["pv_terminal"])
    assert base["equity_value"] == pytest.approx(base["ev"] - 350 + 100 - 10 + 40)
    assert base["per_share"] == pytest.approx(base["equity_value"] / 102)
    assert r["cases"]["bear"]["per_share"] < base["per_share"] < r["cases"]["bull"]["per_share"]
    # WACC on paper: ke = .04 + 1*.05 = .09; E = 20*100 = 2000, D = 350, kd = 20/350, tax .20
    assert r["wacc"]["wacc"] == pytest.approx(2000 / 2350 * 0.09 + 350 / 2350 * (20 / 350) * 0.8)
    assert r["sensitivity"]["per_share"][2][2] == pytest.approx(base["per_share"])
    assert r["comparables"] == {"blocked": "peer list not approved"}
