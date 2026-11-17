import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("guard", Path(__file__).resolve().parents[1] / ".claude/hooks/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def call(tmp, agent, tool, **inp):
    return guard.decide({"agent_type": agent, "tool_name": tool, "tool_input": inp}, root=tmp)


def test_main_session_is_not_restricted_by_the_hook(tmp_path):
    assert guard.decide({"tool_name": "Write", "tool_input": {"file_path": "x.py"}}, root=tmp_path) is None


def test_subagent_writes_only_inside_runs(tmp_path):
    assert call(tmp_path, "forecaster", "Write", file_path=str(tmp_path / "runs/KO/d/assumptions.json")) is None
    assert "only inside runs" in call(tmp_path, "forecaster", "Write", file_path=str(tmp_path / "valuation/dcf.py"))
    assert "only inside runs" in call(tmp_path, "report-writer", "Write", file_path=str(tmp_path / "runs/../CLAUDE.md"))


def test_no_web_for_judgment_agents(tmp_path):
    assert "no web access" in call(tmp_path, "forecaster", "WebSearch", query="x")


def test_lookup_cap_per_agent(tmp_path):
    (tmp_path / "runs").mkdir()
    for _ in range(4):
        assert call(tmp_path, "assumption-reviewer", "Grep", path="evidence/0000021344", pattern="x") is None
    assert "limit of 4" in call(tmp_path, "assumption-reviewer", "Read", file_path="evidence/x.json")
    assert call(tmp_path, "assumption-reviewer", "Read", file_path="runs/KO/d/facts.json") is None   # not evidence
