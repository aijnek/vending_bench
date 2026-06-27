"""Phase 4: ツール層の単体 + 結合シナリオのテスト。"""

from __future__ import annotations

import pytest

from vending_bench.config import EnvConfig
from vending_bench.env.world import WorldState
from vending_bench.tools.api import execute, ToolError


def world() -> WorldState:
    return WorldState.new(EnvConfig(seed=1))


# --------------------------------------------------------------------------- #
# 引数検証・時間進行
# --------------------------------------------------------------------------- #
def test_unknown_tool_raises():
    with pytest.raises(ToolError):
        execute(world(), "nonexistent")


def test_missing_required_arg_raises():
    with pytest.raises(ToolError):
        execute(world(), "set_price", {"slot": "A1"})  # price 欠落


def test_tool_advances_time_within_day():
    w = world()
    before = w.clock.current
    execute(w, "get_inventory")
    assert w.clock.current > before
    assert w.clock.day_index == 0  # 同日内


def test_minute_tools_never_roll_day():
    w = world()
    for _ in range(500):  # 大量に呼んでも日付は変わらない
        execute(w, "list_emails")
    assert w.clock.day_index == 0


# --------------------------------------------------------------------------- #
# 結合: 発注 -> 支払い -> 入庫 -> 補充 -> 価格 -> 売上 -> 現金回収
# --------------------------------------------------------------------------- #
def test_full_business_loop():
    w = world()
    # 1) 検索 → 発注メール
    execute(w, "web_search", {"query": "soda suppliers"})
    execute(w, "send_email", {
        "to": "sales@freshwholesale.com", "subject": "Order",
        "body": "I'd like to place the following order:\n- 30 x Coca-Cola 12oz can",
    })
    # 2) 翌日: 注文確認の返信が届く
    execute(w, "wait_for_next_day")
    assert len(w.orders) == 1
    order = w.orders[0]

    # 3) 支払い
    msg = execute(w, "send_payment", {"to": "sales@freshwholesale.com", "amount": order.total})
    assert "支払いました" in msg
    assert w.ledger.balance < w.config.initial_balance

    # 4) 配送到着まで日送り
    for _ in range(8):
        execute(w, "wait_for_next_day")
        if w.storage.quantity_of("Coca-Cola 12oz can") > 0:
            break
    assert w.storage.quantity_of("Coca-Cola 12oz can") == 30

    # 5) 補充 + 価格設定
    stock_msg = execute(w, "stock_machine", {"slot": "A1", "product": "Coca-Cola 12oz can", "quantity": 15})
    assert "補充" in stock_msg
    assert "A1 [small] Coca-Cola 12oz can x15/15" in execute(w, "get_machine_inventory")
    execute(w, "set_price", {"slot": "A1", "price": 2.0})
    assert w.storage.quantity_of("Coca-Cola 12oz can") == 15  # 15個倉庫に残る

    # 6) 数日売って現金回収
    machine_cash_seen = False
    for _ in range(10):
        execute(w, "wait_for_next_day")
        if w.machine.cash > 0:
            machine_cash_seen = True
            break
    assert machine_cash_seen
    before = w.ledger.balance
    out = execute(w, "collect_cash")
    assert "回収" in out
    assert w.ledger.balance > before
    assert w.machine.cash == 0.0


def test_stock_machine_size_mismatch():
    w = world()
    w.storage.add("Doritos family-size", "large", 10, 1.8)
    out = execute(w, "stock_machine", {"slot": "A1", "product": "Doritos family-size", "quantity": 5})
    assert "small 用" in out or "存在しません" in out  # A1 は small スロット


def test_terminal_blocks_tools():
    w = WorldState.new(EnvConfig(seed=1, initial_balance=1.0, bankruptcy_grace_days=1))
    for _ in range(5):
        execute(w, "wait_for_next_day")
    assert w.status == "bankrupt"
    out = execute(w, "get_inventory")
    assert "終了" in out
