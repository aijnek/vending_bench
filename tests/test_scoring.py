"""Phase 7: スコアリングと集計のテスト。"""

from __future__ import annotations

from vending_bench.config import EnvConfig
from vending_bench.env.world import WorldState
from vending_bench.scoring import score_breakdown, aggregate_runs, RunMetrics


def test_score_breakdown_components_sum_to_net_worth():
    w = WorldState.new(EnvConfig(initial_balance=100.0))
    w.storage.add("Coke", "small", 10, 1.0)            # +10
    w.machine.stock("A1", product_name="Pepsi", size="small", quantity=5, unit_cost=2.0)  # +10
    w.machine.cash = 5.0
    b = score_breakdown(w)
    c = b["components"]
    total = c["cash_balance"] + c["machine_cash"] + c["storage_value"] + c["machine_inventory_value"]
    assert round(total, 2) == b["net_worth"] == 125.0


def test_aggregate_runs():
    agg = aggregate_runs([100.0, 200.0, 300.0])
    assert agg["runs"] == 3
    assert agg["mean"] == 200.0
    assert agg["min"] == 100.0 and agg["max"] == 300.0
    assert agg["stdev"] > 0
    assert aggregate_runs([])["runs"] == 0


def test_run_metrics_records():
    m = RunMetrics()
    m.record_tool("web_search")
    m.record_tool("web_search")
    m.record_day(1, 498.0)
    assert m.tool_counts["web_search"] == 2
    assert m.net_worth_by_day == [(1, 498.0)]
