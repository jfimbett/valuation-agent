import pytest

from pipeline.facts import annual, latest_instant, quarters, ttm


def cf(tag, rows, taxonomy="us-gaap", unit="USD"):
    return {"facts": {taxonomy: {tag: {"units": {unit: rows}}}}}


def row(start, end, val, form, filed, accn="a"):
    r = {"end": end, "val": val, "form": form, "filed": filed, "accn": accn, "fp": "x"}
    if start:
        r["start"] = start
    return r


def test_annual_filters_lookahead_and_scales_to_millions():
    data = cf("Revenues", [row("2024-01-01", "2024-12-31", 47_000e6, "10-K", "2025-02-20"),
                           row("2025-01-01", "2025-12-31", 50_000e6, "10-K", "2026-02-20")])
    got = annual(data, ["Revenues"], "2025-06-30")
    assert [g["end"] for g in got] == ["2024-12-31"]
    assert got[0]["value"] == pytest.approx(47_000)


def test_restatement_latest_filing_wins():
    data = cf("Revenues", [row("2024-01-01", "2024-12-31", 100e6, "10-K", "2025-02-20", "old"),
                           row("2024-01-01", "2024-12-31", 90e6, "10-K", "2026-02-20", "new")])
    assert annual(data, ["Revenues"], "2026-06-30")[0]["accession"] == "new"


ROWS = [row("2025-01-01", "2025-03-31", 90e6, "10-Q", "2025-05-01", "q1"),
        row("2025-01-01", "2025-06-30", 190e6, "10-Q", "2025-08-01", "q2"),
        row("2025-01-01", "2025-09-30", 295e6, "10-Q", "2025-11-01", "q3"),
        row("2025-01-01", "2025-12-31", 400e6, "10-K", "2026-02-20", "fy")]


def test_ytd_converted_to_quarters_and_ttm():
    # Q1 = 90, 6M = 190 -> Q2 = 100, 9M = 295 -> Q3 = 105, FY = 400 -> Q4 = 105; TTM = 400
    qs = quarters(cf("Revenues", ROWS), ["Revenues"], "2026-06-30")
    assert {q["end"]: q["value"] for q in qs} == {"2025-03-31": 90, "2025-06-30": 100,
                                                  "2025-09-30": 105, "2025-12-31": 105}
    t = ttm(qs)
    assert t["value"] == pytest.approx(400) and t["end"] == "2025-12-31"


def test_no_lookahead_in_quarters():
    qs = quarters(cf("Revenues", ROWS), ["Revenues"], "2025-09-01")   # Q3 and FY not yet filed
    assert [q["end"] for q in qs] == ["2025-06-30", "2025-03-31"]


def test_ttm_missing_not_zero():
    rows = [row("2025-01-01", "2025-03-31", 90e6, "10-Q", "2025-05-01")]
    assert ttm(quarters(cf("Revenues", rows), ["Revenues"], "2026-01-01")) is None


def test_latest_instant_respects_date_and_dei_shares():
    data = cf("EntityCommonStockSharesOutstanding",
              [row(None, "2025-10-20", 4300e6, "10-Q", "2025-10-30"),
               row(None, "2026-02-10", 4310e6, "10-K", "2026-02-20")], taxonomy="dei", unit="shares")
    got = latest_instant(data, ["EntityCommonStockSharesOutstanding"], "2026-01-01", taxonomy="dei")
    assert got["value"] == pytest.approx(4300)


def test_missing_tag_is_none():
    assert latest_instant({"facts": {}}, ["Nope"], "2026-01-01") is None


def test_freshest_tag_wins_over_a_stale_first_tag():
    data = {"facts": {"us-gaap": {
        "OldTag": {"units": {"USD": [row("2018-01-01", "2018-12-31", 10e6, "10-K", "2019-02-01")]}},
        "NewTag": {"units": {"USD": [row("2025-01-01", "2025-12-31", 20e6, "10-K", "2026-02-01")]}}}}}
    got = annual(data, ["OldTag", "NewTag"], "2026-06-30")
    assert got[0]["end"] == "2025-12-31" and got[0]["value"] == pytest.approx(20)


def test_q4_from_fy_minus_three_single_quarters_when_no_nine_month_total():
    rows = [row("2025-02-01", "2025-04-30", 100e6, "10-Q", "2025-05-20", "q1"),
            row("2025-05-01", "2025-07-31", 110e6, "10-Q", "2025-08-20", "q2"),
            row("2025-08-01", "2025-10-31", 120e6, "10-Q", "2025-11-20", "q3"),
            row("2025-02-01", "2026-01-31", 450e6, "10-K", "2026-03-20", "fy")]
    qs = quarters(cf("NetIncomeLoss", rows), ["NetIncomeLoss"], "2026-06-30")
    assert qs[0]["end"] == "2026-01-31" and qs[0]["value"] == pytest.approx(120) and qs[0]["kind"] == "derived"


def test_proxy_statement_repeats_are_ignored():
    rows = [row("2025-01-01", "2025-12-31", 100e6, "10-K", "2026-02-20", "k"),
            row("2025-01-01", "2025-12-31", 100e6, "DEF 14A", "2026-04-20", "proxy")]
    got = annual(cf("Revenues", rows), ["Revenues"], "2026-06-30")
    assert got[0]["accession"] == "k"
