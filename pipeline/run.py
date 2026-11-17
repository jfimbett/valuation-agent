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


def start(ticker: str, date: str | None = None) -> Path:
    date = date or dt.date.today().isoformat()
    d = run_dir(ticker, date)
    if d.exists():
        raise SystemExit(f"run already exists: {d}")
    d.mkdir(parents=True)
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


def approve(d: Path, step: str, by: str) -> None:
    s = _load(d)
    if step not in s["done"]:
        raise SystemExit(f"cannot approve '{step}': not done")
    s["approved"].append(step)
    _save(d, s)
    log(d, event="approved", step=step, by=by)


def block(d: Path, reason: str) -> None:
    s = _load(d)
    s["blocked"] = reason
    _save(d, s)
    log(d, event="blocked", reason=reason)
