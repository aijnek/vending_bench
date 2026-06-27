"""Phase 3: サプライヤー・メール・交渉・配送・返金のテスト。"""

from __future__ import annotations

from vending_bench.config import EnvConfig
from vending_bench.env.world import WorldState
from vending_bench.env import events as events_mod
from vending_bench.env.suppliers.catalog import SUPPLIERS, supplier_by_email
from vending_bench.env.suppliers.rule_based import (
    RuleBasedNegotiationEngine, parse_order_lines, extract_target_price, classify_intent,
)
from vending_bench.env.orders import STATUS_PAID, STATUS_DELIVERED, STATUS_FAILED


def world() -> WorldState:
    return WorldState.new(EnvConfig(seed=1))


def send_to(w: WorldState, supplier_id: str, subject: str, body: str):
    s = SUPPLIERS[supplier_id]
    return w.mailbox.add_outgoing(sender=w.config.agent_email, recipient=s.email,
                                  subject=subject, body=body, day=w.clock.day_index, timestamp=w.timestamp)


def overnight(w: WorldState):
    return w.advance_to_next_day(overnight_fn=events_mod.process_overnight)


# --------------------------------------------------------------------------- #
# パーサ
# --------------------------------------------------------------------------- #
def test_parse_order_lines_variants():
    s = SUPPLIERS["fresh"]
    body = "Order:\n- 24 x Coca-Cola 12oz can\n- Pepsi 12oz can: 12\n- 6 Snickers bar"
    parsed = dict(parse_order_lines(body, s))
    assert parsed["Coca-Cola 12oz can"] == 24
    assert parsed["Pepsi 12oz can"] == 12
    assert parsed["Snickers bar"] == 6


def test_extract_target_price_and_intent():
    assert extract_target_price("I want $0.55 per can, your $1.50 is too high") == 0.55
    assert classify_intent("what is your best price?", [], 0.55) == "negotiate"
    assert classify_intent("I'd like to place the following order", [("Coke", 10)], None) == "order"
    assert classify_intent("please send your price list", [], None) == "inquiry"
    # 数量行があり交渉ワードが無ければ、決まり文句が無くても発注扱い
    assert classify_intent("40 x Coca-Cola 12oz can", [("Coca-Cola 12oz can", 40)], None) == "order"
    # 数量行＋交渉ワードは交渉
    assert classify_intent("If I order 100, what's your best price?", [("Coke", 100)], None) == "negotiate"


def test_order_created_without_keyword_phrase():
    """件名 'Order' + 本文に数量行だけ、でも発注が成立する（人間がつまずいたケース）。"""
    w = world()
    send_to(w, "fresh", "Order", "40 x Coca-Cola 12oz can")
    overnight(w)
    assert len(w.orders) == 1
    assert w.orders[0].lines[0].quantity == 40


# --------------------------------------------------------------------------- #
# 返信生成
# --------------------------------------------------------------------------- #
def test_inquiry_gets_pricelist():
    w = world()
    send_to(w, "fresh", "Price list", "Please send your price list for sodas.")
    rep = overnight(w)
    assert rep.overnight.new_email_count == 1
    inbox = w.mailbox.inbox()
    assert any("per unit" in e.body for e in inbox)


def test_negotiation_lowers_price_for_honest():
    w = world()
    s = SUPPLIERS["bunch"]
    eng = RuleBasedNegotiationEngine()
    # 初回見積
    p0 = eng._quote(s, "Coca-Cola 12oz can", 0)
    # 数ラウンド交渉
    w.supplier_runtime[s.supplier_id] = {"round": 3, "out_of_business": False}
    p3 = eng._quote(s, "Coca-Cola 12oz can", 3)
    assert p3 < p0


def test_scam_barely_moves():
    eng = RuleBasedNegotiationEngine()
    s = SUPPLIERS["vendmart"]
    p0 = eng._quote(s, "Coca-Cola 12oz can", 0)
    p5 = eng._quote(s, "Coca-Cola 12oz can", 5)
    # 下げても適正価格よりずっと高い（floor_markup>=2.0）
    from vending_bench.env.suppliers.catalog import PRODUCTS
    assert p5 >= PRODUCTS["Coca-Cola 12oz can"].fair_price * 2.0
    assert p5 <= p0


# --------------------------------------------------------------------------- #
# 発注 -> 支払い -> 配送（正直系）
# --------------------------------------------------------------------------- #
def test_order_payment_delivery_friendly():
    w = world()
    send_to(w, "fresh", "Order", "I'd like to place the following order:\n- 24 x Coca-Cola 12oz can")
    overnight(w)  # 注文確認の返信 + PendingOrder 作成
    assert len(w.orders) == 1
    order = w.orders[0]
    assert order.total > 0

    # 支払い処理（残高控除はツール層だが、ここでは紐付けのみ検証）
    ok, msg = events_mod.register_payment(w, "sales@freshwholesale.com", order.total)
    assert ok and order.status == STATUS_PAID and order.arrival_day is not None

    # 到着日まで進める
    for _ in range(8):
        overnight(w)
        if order.status == STATUS_DELIVERED:
            break
    assert order.status == STATUS_DELIVERED
    assert w.storage.quantity_of("Coca-Cola 12oz can") == 24


def test_underpayment_rejected():
    w = world()
    send_to(w, "fresh", "Order", "I'd like to place the following order:\n- 10 x Pepsi 12oz can")
    overnight(w)
    order = w.orders[0]
    ok, _ = events_mod.register_payment(w, "sales@freshwholesale.com", order.total - 5.0)
    assert not ok


# --------------------------------------------------------------------------- #
# bait_and_switch: 支払い後に届かない
# --------------------------------------------------------------------------- #
def test_bait_and_switch_fails_delivery():
    w = WorldState.new(EnvConfig(seed=7))
    send_to(w, "quick", "Order", "I'd like to place the following order:\n- 50 x Coca-Cola 12oz can")
    overnight(w)
    order = w.orders[0]
    events_mod.register_payment(w, "deals@quicksupply.com", order.total)
    delivered = False
    for _ in range(12):
        overnight(w)
        if order.status in (STATUS_DELIVERED, STATUS_FAILED):
            delivered = order.status == STATUS_DELIVERED
            break
    # reliability 0.10 なのでほぼ失敗するはず（このシードで確認）
    assert order.status == STATUS_FAILED
    assert not delivered
    assert w.storage.quantity_of("Coca-Cola 12oz can") == 0


# --------------------------------------------------------------------------- #
# 返金イベント
# --------------------------------------------------------------------------- #
def test_refund_event_deducts_balance():
    # 返金確率を 1.0 にして必ず発生させる
    w = WorldState.new(EnvConfig(seed=2, refund_daily_probability=1.0))
    start = w.ledger.balance
    rep = overnight(w)
    refunds = [t for t in w.ledger.transactions if t.kind == "refund"]
    assert len(refunds) == 1
    assert w.ledger.balance < start
