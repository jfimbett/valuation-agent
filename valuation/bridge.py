"""Enterprise value to equity value per share. All inputs must share one date, one unit (USD millions)."""
from __future__ import annotations

from dataclasses import dataclass

from .dcf import ValuationError


@dataclass(frozen=True)
class Bridge:
    debt: float
    cash: float                       # cash and short-term investments
    noncontrolling_interests: float = 0.0
    preferred: float = 0.0
    equity_method_investments: float = 0.0   # added back: not in FCFF
    as_of: str = ""                   # ISO date of the balance sheet
    diluted_shares: float = 0.0       # millions

    def net_debt(self) -> float:
        return self.debt - self.cash

    def equity_value(self, ev: float) -> float:
        return (ev - self.debt + self.cash - self.noncontrolling_interests - self.preferred
                + self.equity_method_investments)

    def per_share(self, ev: float) -> float:
        if self.diluted_shares <= 0:
            raise ValuationError("diluted share count missing or non-positive: this blocks the report")
        return self.equity_value(ev) / self.diluted_shares
