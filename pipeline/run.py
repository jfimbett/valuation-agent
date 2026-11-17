"""Run folder, run log and the gatekeeper behind `python -m pipeline start|next|done|approve|block`."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .steps import ARTIFACT, STEPS

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_dir(ticker: str, date: str) -> Path:
    return RUNS / ticker.upper() / date


def _state_path(d: Path) -> Path:
    return d / "state.json"


def _load(d: Path) -> dict:
    return json.loads(_state_path(d).read_text())


def _save(d: Path, state: dict) -> None:
    _state_path(d).write_text(json.dumps(state, indent=2))


def log(d: Path, **event) -> None:
    with (d / "run-log.jsonl").open("a") as f:
        f.write(json.dumps({"t": _now(), **event}) + "\n")


def start(ticker: str, date: str | None = None, fresh: bool = False) -> Path:
    """Create the run folder. If one exists, stop (so a finished or half-done run is never continued by accident);
    with fresh=True the old folder is moved to runs/_old/ and a new run begins."""
    date = date or dt.date.today().isoformat()
    d = run_dir(ticker, date)
    if d.exists():
        if not fresh:
            raise SystemExit(f"run already exists: {d}. Continue it with `next`, or start over with `start --fresh`.")
        old = RUNS / "_old"
        old.mkdir(exist_ok=True)
        n = len(list(old.glob(f"{ticker.upper()}-{date}-*"))) + 1
        d.rename(old / f"{ticker.upper()}-{date}-{n}")
    d.mkdir(parents=True)
    for f in RUNS.glob(".lookups-*.json"):   # lookup counters used by .claude/hooks/guard.py restart with each run
        f.unlink()
    _save(d, {"ticker": ticker.upper(), "date": date, "done": [], "approved": [], "blocked": None})
    log(d, event="start", ticker=ticker.upper(), date=date)
    return d


def next_step(d: Path) -> dict:
    """The only step allowed next, or the reason the run is blocked, waiting for the user, or done."""
    s = _load(d)
    if s["blocked"]:
        return {"action": "blocked", "reason": s["blocked"]}
    for step in STEPS:
        n = step["name"]
        if n not in s["done"]:
            return {"action": "do", "step": n, "by": step["by"], "command": step["command"],
                    "writes": ARTIFACT[n]}
        if step["gate"] and n not in s["approved"]:
            return {"action": "ask the user", "after": n, "question": step["gate"]}
    return {"action": "done"}


def mark_done(d: Path, step: str) -> None:
    """Refuse out-of-order completion and a missing artifact: every artifact must exist before the next step."""
    nxt = next_step(d)
    if nxt.get("action") != "do" or nxt["step"] != step:
        raise SystemExit(f"step '{step}' is not allowed now: {nxt}")
    if not (d / ARTIFACT[step]).exists():
        raise SystemExit(f"{ARTIFACT[step]} was not written; step '{step}' is not done")
    s = _load(d)
    s["done"].append(step)
    _save(d, s)
    log(d, event="done", step=step)


def approve(d: Path, step: str, by: str, drop: list[str] | None = None) -> None:
    """A person approves a step. At the review gate this also approves the assumptions and the peer list
    (the user may drop peers). Only this command sets those flags."""
    s = _load(d)
    if step not in s["done"]:
        raise SystemExit(f"cannot approve '{step}': not done")
    if step == "review":
        blocks = json.loads((d / "checks.json").read_text())["blocks"]
        if blocks:
            raise SystemExit(f"cannot approve: checks.json has {blocks} blocking item(s); fix them first")
        a = json.loads((d / "assumptions.json").read_text())
        a["status"] = "approved"
        (d / "assumptions.json").write_text(json.dumps(a, indent=2))
        if (d / "peers.json").exists():
            p = json.loads((d / "peers.json").read_text())
            if p.get("selected"):
                p["selected"] = [x for x in p["selected"] if x["ticker"] not in (drop or [])]
                p["dropped_by_user"] = drop or []
                p["approved"] = True
                p["approved_by"] = by
                (d / "peers.json").write_text(json.dumps(p, indent=2))
    s["approved"].append(step)
    _save(d, s)
    log(d, event="approved", step=step, by=by, dropped_peers=drop or [])


def unblock(d: Path, why: str) -> None:
    """Lift a block after the cause was fixed (logged). The checker, not the session, decides what runs next."""
    s = _load(d)
    s["blocked"] = None
    _save(d, s)
    log(d, event="unblocked", why=why)


def block(d: Path, reason: str) -> None:
    s = _load(d)
    s["blocked"] = reason
    _save(d, s)
    log(d, event="blocked", reason=reason)


DRAFTS = {"assumptions": ("assumptions.draft.json", "assumptions.json"),
          "report": ("report.draft.md", "report.md"),
          "history-comment": ("history-comment.draft.md", "history-comment.md")}


def accept(d: Path, name: str) -> None:
    """Subagents return text; the session saves it unchanged as a draft; this validates it and writes the real file.
    So Python is the only writer of the saved artifacts."""
    if name not in DRAFTS:
        raise SystemExit(f"unknown artifact '{name}'; choose from {sorted(DRAFTS)}")
    draft, final = DRAFTS[name]
    if not (d / draft).exists():
        raise SystemExit(f"{draft} not found in {d}")
    text = (d / draft).read_text(encoding="utf-8").strip()
    if text.startswith("```"):   # a code fence around JSON is tolerated; nothing else is changed
        text = text.split(chr(10), 1)[1].rsplit("```", 1)[0].strip()
    if name == "assumptions":
        a = json.loads(text)
        if not isinstance(a.get("items"), list) or not a["items"] or "terminal_growth" not in a:
            raise SystemExit("assumptions need `items` and `terminal_growth`")
        a["status"] = "proposed"   # only the gate approves
        text = json.dumps(a, indent=2)
    elif not text:
        raise SystemExit(f"{draft} is empty")
    (d / final).write_text(text, encoding="utf-8")
    log(d, event="accepted", artifact=name, draft=draft)
