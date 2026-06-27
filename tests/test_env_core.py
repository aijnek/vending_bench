"""Phase 1: 環境コア（残高・手数料・破産・在庫・自販機・永続化）のテスト。"""

from __future__ import annotations

from dataclasses import replace

from vending_bench.config import EnvConfig
from vending_bench.env.world import WorldState, DaySalesResult


def fresh(**overrides) -> WorldState:
    cfg = EnvConfig(**overrides) if overrides else EnvConfig()
    return WorldState.new(cfg)


# --------------------------------------------------------------------------- #
# 手数料・残高
# --------------------------------------------------------------------------- #
def test_daily_fee_deducted_each_day():
    w = fresh()
    start = w.ledger.balance
    w.advance_to_next_day()
    assert w.ledger.balance == start - w.config.daily_fee
    assert w.clock.day_index == 1


def test_bankruptcy_after_grace_days():
    # 残高を手数料1日分未満にして連続未払いを発生させる
    w = fresh(initial_balance=1.0, bankruptcy_grace_days=10)
    for _ in range(w.config.bankruptcy_grace_days):
        w.advance_to_next_day()
        assert w.status == "running"
    # grace を超える日でも払えず破産
    w.advance_to_next_day()
    assert w.ledger.consecutive_unpaid_fee_days == w.config.bankruptcy_grace_days + 1
    assert w.status == "bankrupt"


def test_no_advance_when_terminal():
    w = fresh(initial_balance=1.0, bankruptcy_grace_days=1)
    for _ in range(5):
        w.advance_to_next_day()
    assert w.status == "bankrupt"
    day_at_bankrupt = w.clock.day_index
    w.advance_to_next_day()
    assert w.clock.day_index == day_at_bankrupt  # 進まない


def test_completion_at_duration():
    w = fresh(duration_days=3, initial_balance=1000.0)
    for _ in range(3):
        w.advance_to_next_day()
    assert w.status == "completed"


# --------------------------------------------------------------------------- #
# クレジット入金遅延
# --------------------------------------------------------------------------- #
def test_credit_settles_next_day():
    w = fresh()
    # 当日売上(クレジット$50)を計上する sales_fn
    def sales_fn(world):
        world.ledger.add_credit_sale(50.0, settle_day=world.clock.day_index + world.config.credit_settlement_days)
        return DaySalesResult(units_sold=1, revenue_credit=50.0)

    start = w.ledger.balance
    w.advance_to_next_day(sales_fn=sales_fn)
    # 翌朝に入金され、手数料も引かれている
    assert w.ledger.balance == start + 50.0 - w.config.daily_fee


# --------------------------------------------------------------------------- #
# トークン課金
# --------------------------------------------------------------------------- #
def test_token_billing_weekly():
    w = fresh(token_billing_period_days=7)
    w.ledger.record_output_tokens(1_000_000)  # $100 相当
    billed_total = 0.0
    for _ in range(7):
        rep = w.advance_to_next_day()
        billed_total += rep.tokens_billed
    assert round(billed_total, 2) == 100.0
    assert w.ledger.output_tokens_unbilled == 0


# --------------------------------------------------------------------------- #
# 倉庫在庫
# --------------------------------------------------------------------------- #
def test_storage_weighted_average_cost():
    w = fresh()
    w.storage.add("Coke", "small", 10, 1.00)
    w.storage.add("Coke", "small", 10, 2.00)
    item = w.storage.items["Coke"]
    assert item.quantity == 20
    assert item.unit_cost == 1.5
    assert w.storage.value() == 30.0
    taken = w.storage.remove("Coke", 25)
    assert taken == 20
    assert "Coke" not in w.storage.items


# --------------------------------------------------------------------------- #
# 自販機
# --------------------------------------------------------------------------- #
def test_machine_layout_and_size_rules():
    w = fresh()
    assert len(w.machine.slots) == 12
    assert {s.label for s in w.machine.slots} >= {"A1", "B3", "C1", "D3"}
    # A行は small、C行は large
    assert w.machine.get_slot("A1").size_class == "small"
    assert w.machine.get_slot("C1").size_class == "large"
    # large 商品を small スロットに補充は失敗
    added, _ = w.machine.stock("A1", product_name="Big", size="large", quantity=5, unit_cost=1.0)
    assert added == 0


def test_machine_stock_capacity_and_cash():
    w = fresh()
    cap = w.machine.get_slot("A1").capacity
    added, _ = w.machine.stock("A1", product_name="Coke", size="small", quantity=cap + 100, unit_cost=1.0)
    assert added == cap
    ok, _ = w.machine.set_price("A1", 2.5)
    assert ok
    slot = w.machine.get_slot("A1")
    w.machine.record_sale(slot, 3, cash_amount=7.5)
    assert slot.quantity == cap - 3
    assert w.machine.cash == 7.5
    assert w.machine.collect_cash() == 7.5
    assert w.machine.cash == 0.0


# --------------------------------------------------------------------------- #
# net worth
# --------------------------------------------------------------------------- #
def test_net_worth_components():
    w = fresh(initial_balance=100.0)
    w.storage.add("Coke", "small", 10, 1.0)  # +10
    w.machine.stock("A1", product_name="Pepsi", size="small", quantity=5, unit_cost=2.0)  # +10
    w.machine.cash = 5.0
    assert w.net_worth() == 100.0 + 10.0 + 10.0 + 5.0


# --------------------------------------------------------------------------- #
# 永続化
# --------------------------------------------------------------------------- #
def test_persistence_roundtrip(tmp_path):
    w = fresh()
    w.storage.add("Coke", "small", 10, 1.25)
    w.machine.stock("A1", product_name="Coke", size="small", quantity=5, unit_cost=1.25)
    w.machine.set_price("A1", 2.5)
    w.advance_to_next_day()
    p = tmp_path / "state.json"
    w.save(p)
    loaded = WorldState.load(p)
    assert loaded.to_dict() == w.to_dict()
    assert loaded.net_worth() == w.net_worth()
    assert loaded.clock.day_index == w.clock.day_index
