"""The fixed order of the run. Each step: name, who does it, and whether a person must approve afterwards."""
STEPS = [
    {"name": "fetch",    "by": "python",   "command": "python -m pipeline.fetch",   "gate": None},
    {"name": "read",     "by": "python+subagent:reader", "command": "python -m pipeline.read", "gate": None},
    {"name": "history",  "by": "python+subagent:reader", "command": "python -m pipeline.history", "gate": None},
    {"name": "forecast", "by": "subagent:forecaster", "command": None, "gate": None},
    {"name": "review",   "by": "python+subagent:assumption-reviewer", "command": "python -m pipeline.checks", "gate": "ask the user: peers and open warnings"},
    {"name": "value",    "by": "python",   "command": "python -m pipeline.value",   "gate": None},
    {"name": "report",   "by": "subagent:report-writer", "command": None, "gate": "ask the user: publish"},
]
ARTIFACT = {"fetch": "evidence.json", "read": "facts.json", "history": "history.json",
            "forecast": "assumptions.json", "review": "checks.json", "value": "valuation.json", "report": "report.md"}
