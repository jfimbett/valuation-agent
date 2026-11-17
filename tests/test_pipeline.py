import json

import pytest

from pipeline import run


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "RUNS", tmp_path)
    return run.start("ko", "2026-11-17")


def test_order_is_enforced(d):
    assert run.next_step(d)["step"] == "fetch"
    with pytest.raises(SystemExit):
        run.mark_done(d, "read")            # out of order


def test_done_requires_the_artifact(d):
    with pytest.raises(SystemExit):
        run.mark_done(d, "fetch")           # evidence.json not written
    (d / "evidence.json").write_text("{}")
    run.mark_done(d, "fetch")
    assert run.next_step(d)["step"] == "read"


def test_gates_stop_for_the_user_and_blocks_win(d):
    for step, art in [("fetch", "evidence.json"), ("read", "facts.json"), ("history", "history.json"),
                      ("forecast", "assumptions.json"), ("review", "checks.json")]:
        (d / art).write_text("{}"); run.mark_done(d, step)
    assert run.next_step(d)["action"] == "ask the user"
    run.approve(d, "review", by="tester")
    assert run.next_step(d)["step"] == "value"
    run.block(d, "share count missing")
    assert run.next_step(d) == {"action": "blocked", "reason": "share count missing"}
    assert "approved" in (d / "run-log.jsonl").read_text()


def test_start_refuses_existing_run_and_fresh_archives_it(d, tmp_path):
    with pytest.raises(SystemExit):
        run.start("ko", "2026-11-17")
    (d / "marker.txt").write_text("old")
    new = run.start("ko", "2026-11-17", fresh=True)
    assert new == d and not (new / "marker.txt").exists()
    assert (tmp_path / "_old" / "KO-2026-11-17-1" / "marker.txt").exists()


def test_accept_validates_and_python_writes_the_artifact(d):
    (d / "assumptions.draft.json").write_text('```json\n{"status": "approved", "terminal_growth": {"value": 0.02}, "items": [{"id": "a"}]}\n```')
    run.accept(d, "assumptions")
    a = json.loads((d / "assumptions.json").read_text())
    assert a["status"] == "proposed"          # a subagent can never self-approve
    (d / "assumptions.draft.json").write_text('{"items": []}')
    with pytest.raises(SystemExit):
        run.accept(d, "assumptions")
    (d / "report.draft.md").write_text("# KO report\n")
    run.accept(d, "report")
    assert (d / "report.md").read_text() == "# KO report"
    with pytest.raises(SystemExit):
        run.accept(d, "valuation")            # only drafts of these three artifacts can be accepted
