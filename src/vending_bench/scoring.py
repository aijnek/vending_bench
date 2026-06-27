"""スコアリングとランのメトリクス集計。

主指標は net worth（VB の最終純資産）。内訳・運用メトリクス・複数ラン集計を提供する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev

from .env.world import WorldState


def score_breakdown(world: WorldState) -> dict:
    """net worth の内訳と主要メトリクスを返す。"""
    return {
        "net_worth": world.net_worth(),
        "components": {
            "cash_balance": round(world.ledger.balance, 2),
            "machine_cash": round(world.machine.cash, 2),
            "storage_value": world.storage.value(),
            "machine_inventory_value": world.machine.value(),
        },
        "pending_credit": round(sum(c.amount for c in world.ledger.pending_credits), 2),
        "day": world.clock.day_index,
        "status": world.status,
        "units_sold": world.total_units_sold,
        "revenue_total": world.total_revenue,
        "fees_unpaid_streak": world.ledger.consecutive_unpaid_fee_days,
        "output_tokens_unbilled": world.ledger.output_tokens_unbilled,
        "open_orders": len([o for o in world.orders if o.status in ("awaiting_payment", "paid")]),
    }


@dataclass
class RunMetrics:
    """1ランの時系列メトリクス（loop が日次で append する）。"""
    net_worth_by_day: list[tuple[int, float]] = field(default_factory=list)
    tool_counts: dict[str, int] = field(default_factory=dict)

    def record_day(self, day: int, net_worth: float) -> None:
        self.net_worth_by_day.append((day, round(net_worth, 2)))

    def record_tool(self, tool: str) -> None:
        self.tool_counts[tool] = self.tool_counts.get(tool, 0) + 1

    def to_dict(self) -> dict:
        return {"net_worth_by_day": self.net_worth_by_day, "tool_counts": self.tool_counts}


def aggregate_runs(scores: list[float]) -> dict:
    """複数ランの net worth を集計（VB は 5 ラン平均）。"""
    if not scores:
        return {"runs": 0}
    return {
        "runs": len(scores),
        "mean": round(mean(scores), 2),
        "min": round(min(scores), 2),
        "max": round(max(scores), 2),
        "stdev": round(pstdev(scores), 2) if len(scores) > 1 else 0.0,
    }
