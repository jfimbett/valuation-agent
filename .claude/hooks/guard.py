"""PreToolUse hook: hard limits for the subagents, enforced by code, not by prompts.

For calls made inside a subagent (payload has agent_type):
- Write/Edit only under runs/ (the run folder), never anywhere else;
- no web tools for forecaster, assumption-reviewer, reader;
- at most N lookups in evidence/ per subagent per run (forecaster 6, assumption-reviewer 4), counted in runs/.lookups-<agent>.json
  (reset by `python -m pipeline start`).
The main session is not restricted here; it is limited by .claude/settings.json permissions.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOOKUP_LIMITS = {"forecaster": 6, "assumption-reviewer": 4}
NO_WEB = {"forecaster", "assumption-reviewer", "reader", "history-commenter", "report-writer"}
WEB_TOOLS = {"WebFetch", "WebSearch"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}


def decide(payload: dict, root: Path = ROOT) -> str | None:
    """Return a reason to deny, or None to allow."""
    agent = payload.get("agent_type") or payload.get("subagent_type")
    if not agent:
        return None
    tool, inp = payload.get("tool_name", ""), payload.get("tool_input", {}) or {}
    if tool in WEB_TOOLS and agent in NO_WEB:
        return f"{agent} has no web access"
    if tool in WRITE_TOOLS:
        target = Path(inp.get("file_path") or inp.get("notebook_path") or "")
        try:
            (root / target if not target.is_absolute() else target).resolve().relative_to((root / "runs").resolve())
        except ValueError:
            return f"{agent} may write only inside runs/ (tried {target})"
    if tool in READ_TOOLS and agent in LOOKUP_LIMITS:
        path = str(inp.get("file_path") or inp.get("path") or inp.get("pattern") or "")
        if "evidence" in path.replace("\\", "/"):
            f = root / "runs" / f".lookups-{agent}.json"
            n = (json.loads(f.read_text())["n"] if f.exists() else 0) + 1
            if n > LOOKUP_LIMITS[agent]:
                return f"{agent} reached its limit of {LOOKUP_LIMITS[agent]} evidence lookups"
            f.parent.mkdir(exist_ok=True)
            f.write_text(json.dumps({"n": n}))
    return None


if __name__ == "__main__":
    reason = decide(json.load(sys.stdin))
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
