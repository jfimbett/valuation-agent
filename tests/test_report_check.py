from pipeline.report_check import check_report, matches, numbers_in

ART = [{"cases": {"base": {"per_share": 96.9486, "terminal_share": 0.8812}}, "wacc": {"wacc": 0.05264}, "ev": 412345.6}]
CHECKS = {"checks": [{"target": "terminal_growth", "severity": "warn"}, {"target": "x", "severity": "pass"}]}


def test_matching_rounds_percentages_and_billions():
    pool = [96.9486, 0.05264, 412345.6]
    assert matches("$96.95", pool) and matches("5.3%", pool) and matches("412.3", pool) and matches("412,346", pool)
    assert not matches("97.50", pool)


def test_years_dates_and_backticked_ids_are_ignored():
    toks = numbers_in("In 2025 (2026-11-17) see `rev_fy2025` and 96.95")
    assert [t for t in toks if not matches(t, [])] == ["96.95"]


def test_a_changed_number_is_rejected_and_warnings_must_appear():
    good = check_report("Base value $96.95 per share; WACC 5.3%. Limit: `terminal_growth`.", ART, CHECKS)
    assert good["ok"]
    bad = check_report("Base value $99.10 per share.", ART, CHECKS)
    assert bad["unmatched_numbers"] == ["$99.10"] and bad["warnings_missing_from_report"] == ["terminal_growth"]
    assert not bad["ok"]
