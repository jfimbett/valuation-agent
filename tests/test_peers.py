import pytest

from pipeline.peers import distance, rank


def m(t, cap, g, mar, lev):
    return {"ticker": t, "market_cap": cap, "revenue_growth": g, "operating_margin": mar, "leverage": lev}


def test_closest_peer_ranks_first_and_missing_metrics_are_dropped():
    target = m("T", 1000, 0.05, 0.20, 0.3)
    cands = [m("far", 10, 0.5, 0.0, 2.0), m("near", 1100, 0.05, 0.21, 0.3), m("mid", 500, 0.03, 0.15, 0.5),
             {"ticker": "bad", "market_cap": 100, "revenue_growth": None, "operating_margin": 0.1, "leverage": 0.1}]
    r = rank(target, cands, n=2)
    assert [p["ticker"] for p in r["selected"]] == ["near", "mid"]
    assert r["not_selected"] == ["far"] and r["dropped"][0]["ticker"] == "bad"


def test_distance_is_zero_for_identical():
    a = m("A", 1000, 0.05, 0.2, 0.3)
    assert distance(a, a) == pytest.approx(0)
