# valuation-agent

Value a US-listed, non-financial company (10-K and 10-Q filers) with Claude Code: SEC EDGAR filings, Yahoo Finance market
data and an optional FRED risk-free rate in; a sourced valuation report (DCF in three cases, trading multiples, sensitivity
table, limitations) out. Built for the course "Programming and AI for Corporate Finance". A teaching tool, not investment advice.

## Set up (once)

1. Install Python 3.11+ (Anaconda is fine), git and Claude Code. Clone this repository and open it in Claude Code.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and set `SEC_USER_AGENT` to a project name and your own contact email (the SEC requires
   a declared contact). Never commit `.env`.
4. Risk-free rate, two options:
   - set `FRED_API_KEY` in `.env` (free key from a FRED account), or
   - without a key, type today's 10-year Treasury yield into `settings.yaml` as `discount_rate.risk_free_rate_manual`
     (for example `0.042`). The report then says the rate was typed by hand.
5. `python -m pytest -q` should pass.

## Run

In Claude Code: `/value-company KO` (or `/value-company KO 2026-11-17`). The command starts a run folder
`runs/KO/<date>/` and follows `python -m pipeline next`. It stops twice for you: after the review (approve the assumptions
and the five peers; you may drop peers) and after the report (publish or not). Your own Claude Code usage pays for the
AI steps. Companies that are banks, insurers or REITs are refused.

## What is where

| Folder | Content |
|---|---|
| `.claude/skills/value-company/` | the command: the fixed order of work |
| `.claude/agents/` | subagents: forecaster, assumption-reviewer (Opus, high); reader, report-writer (Sonnet, medium); history-commenter (Haiku, low) |
| `.claude/hooks/guard.py` | hard limits: subagents write only in `runs/`, no web, evidence lookup caps |
| `pipeline/` | the Python checker, downloads, checks, report-number check |
| `valuation/` | DCF, bridge, multiples, sensitivity (tested by hand-checked cases) |
| `tests/` | known answers and planted errors; fixtures are synthetic (Synthetic Beverage Co.) |
| `evidence/` | saved filings and data with SHA-256 hashes, never edited |
| `runs/<TICKER>/<date>/` | facts, assumptions, checks, valuation, report, run log |
| `settings.yaml` | risk premium 5.0%, 5 peers, 5% / 1% stop and warn, limits |

## Settings that the course fixed

CAPM with the 10-year Treasury, a 5-year monthly Yahoo beta against the S&P 500 and a 5.0% equity risk premium; cost of
debt = interest expense / debt; five explicit years plus a terminal value; base, bear and bull; peers by industry code,
size, growth, margin and leverage (the user approves them). Terminal growth defaults to 2.5% (proposed), capped at the
risk-free rate and at 4%.

## Data and terms

- SEC EDGAR: declared User-Agent, at most 10 requests per second.
- Yahoo Finance through `yfinance`: not affiliated with or endorsed by Yahoo; research and educational use only.
- FRED (optional): "This product uses the FRED(R) API but is not endorsed or certified by the Federal Reserve Bank of St. Louis."

## Known limits

Peer market data is current, not as of the valuation date. Balance-sheet tags a company stopped using are flagged as
missing, not added as zero. Reports can vary between runs because AI steps vary; saved inputs and the code version are
logged so a run can be checked. The hooks and subagent limits have unit tests but have not been exercised in a live
subagent session yet.
