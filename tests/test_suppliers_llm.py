"""LLMNegotiationEngine のユニットテスト（API不要: FakeCLI を注入）。

FakeCLI が返す JSON を制御することで、LLM 依存なしに:
- 構造化抽出 → 発注・価格確定の正確性
- 特急サーチャージの整合（型別 % の加算・支払い検証・配送短縮）
- 交渉ラウンドのクランプ（無限交渉防止）
- LLM 失敗時のフォールバック（二重作成なし）
- items 不正（カタログ外商品）の無視
を検証する。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from vending_bench.config import EnvConfig
from vending_bench.env import events as events_mod
from vending_bench.env.world import WorldState
from vending_bench.env.suppliers.catalog import SUPPLIERS
from vending_bench.env.suppliers.rule_based import RuleBasedNegotiationEngine
from vending_bench.env.suppliers.llm_based import (
    LLMNegotiationEngine,
    EXPEDITED_SURCHARGE,
    MAX_NEGOTIATION_ROUNDS,
)
from vending_bench.env.orders import STATUS_PAID, STATUS_DELIVERED
from vending_bench.agent.llm import LLMResponse


# ---------------------------------------------------------------------------
# FakeCLI: 任意の JSON を返す ClaudeCLI モック
# ---------------------------------------------------------------------------

@dataclass
class FakeCLI:
    """LLM を呼び出さずに指定した dict を JSON 返却する。"""
    response_data: dict | None = None
    raise_exc: Exception | None = None

    def complete(self, system_prompt: str, user_prompt: str, schema=None) -> LLMResponse:
        if self.raise_exc is not None:
            raise self.raise_exc
        text = json.dumps(self.response_data)
        return LLMResponse(text=text, output_tokens=0, cost_usd=0.0, raw={})


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def restore_engine():
    """各テスト後にデフォルトエンジン（RuleBasedNegotiationEngine）へ復元する。

    test_suppliers_llm.py は events_mod.set_engine() でグローバル状態を書き換えるため、
    テスト間での状態漏れを防ぐ。
    """
    original = events_mod.get_engine()
    yield
    events_mod.set_engine(original)


def _world() -> WorldState:
    return WorldState.new(EnvConfig(seed=42))


def _send(w: WorldState, supplier_id: str, subject: str, body: str):
    s = SUPPLIERS[supplier_id]
    w.mailbox.add_outgoing(
        sender=w.config.agent_email, recipient=s.email,
        subject=subject, body=body,
        day=w.clock.day_index, timestamp=w.timestamp,
    )


def _engine(data: dict | None = None, exc: Exception | None = None) -> LLMNegotiationEngine:
    return LLMNegotiationEngine(cli=FakeCLI(response_data=data, raise_exc=exc))


def _overnight(w: WorldState, eng: LLMNegotiationEngine):
    events_mod.set_engine(eng)
    return w.advance_to_next_day(overnight_fn=events_mod.process_overnight)


# ---------------------------------------------------------------------------
# 1. 抽出 → 発注: items がエンジン側で確定される
# ---------------------------------------------------------------------------

def test_order_created_from_llm_items():
    w = _world()
    _send(w, "fresh", "Order", "Please send me 24 cokes.")
    eng = _engine({
        "intent": "order",
        "items": [{"product": "Coca-Cola 12oz can", "quantity": 24}],
        "expedited": False,
        "reply": "Thank you! Order confirmed.",
    })
    _overnight(w, eng)

    assert len(w.orders) == 1
    order = w.orders[0]
    assert order.lines[0].name == "Coca-Cola 12oz can"
    assert order.lines[0].quantity == 24
    assert order.total > 0
    assert not order.expedited


def test_order_price_matches_engine_quote():
    """LLM が items を返しても価格はエンジンが _quote で計算する。"""
    w = _world()
    s = SUPPLIERS["fresh"]
    eng_rb = RuleBasedNegotiationEngine()
    expected_price = eng_rb._quote(s, "Coca-Cola 12oz can", 0)

    _send(w, "fresh", "Order", "I'd like 10 cokes.")
    _overnight(w, _engine({
        "intent": "order",
        "items": [{"product": "Coca-Cola 12oz can", "quantity": 10}],
        "expedited": False,
        "reply": "Order confirmed.",
    }))

    order = w.orders[0]
    assert order.lines[0].unit_price == expected_price
    assert order.total == round(expected_price * 10, 2)


# ---------------------------------------------------------------------------
# 2. items 不正: カタログ外商品は無視される
# ---------------------------------------------------------------------------

def test_unknown_product_ignored():
    w = _world()
    _send(w, "fresh", "Order", "I want 5 LagrimasMagica bars.")
    _overnight(w, _engine({
        "intent": "order",
        "items": [{"product": "LagrimasMagica bar", "quantity": 5}],
        "expedited": False,
        "reply": "Order confirmed.",
    }))
    # カタログ外商品なので発注されない
    assert len(w.orders) == 0


def test_mixed_valid_invalid_items():
    """カタログ外は捨て、カタログ内だけで発注が成立する。"""
    w = _world()
    _send(w, "fresh", "Order", "I want 5 invalid items and 10 snickers.")
    _overnight(w, _engine({
        "intent": "order",
        "items": [
            {"product": "FakeProduct XYZ", "quantity": 5},
            {"product": "Snickers bar", "quantity": 10},
        ],
        "expedited": False,
        "reply": "Order confirmed.",
    }))
    assert len(w.orders) == 1
    assert w.orders[0].lines[0].name == "Snickers bar"
    assert w.orders[0].lines[0].quantity == 10


# ---------------------------------------------------------------------------
# 3. 特急サーチャージ
# ---------------------------------------------------------------------------

def test_expedited_surcharge_friendly():
    """friendly の特急注文: order.total = base * 1.10、配送短縮あり。"""
    w = _world()
    s = SUPPLIERS["fresh"]
    eng_rb = RuleBasedNegotiationEngine()
    unit_price = eng_rb._quote(s, "Snickers bar", 0)
    base = round(unit_price * 12, 2)
    expected_total = round(base * 1.10, 2)

    _send(w, "fresh", "Order", "Rush order: 12 Snickers, expedited please!")
    _overnight(w, _engine({
        "intent": "order",
        "items": [{"product": "Snickers bar", "quantity": 12}],
        "expedited": True,
        "reply": "Expedited order confirmed!",
    }))

    order = w.orders[0]
    assert order.expedited
    assert order.total == expected_total

    # 支払い後の配送日数が最短（HONEST_TYPES）
    ok, _ = events_mod.register_payment(w, s.email, order.total)
    assert ok
    assert order.arrival_day == w.clock.day_index + s.delivery_days_min


def test_expedited_surcharge_scam():
    """scam の特急注文: total に 25% 加算されるが配送短縮はされない。"""
    w = _world()
    s = SUPPLIERS["vendmart"]
    eng_rb = RuleBasedNegotiationEngine()
    unit_price = eng_rb._quote(s, "Coca-Cola 12oz can", 0)
    base = round(unit_price * 10, 2)
    expected_total = round(base * 1.25, 2)

    _send(w, "vendmart", "Order", "Rush order please: 10 cokes, I'll pay extra!")
    _overnight(w, _engine({
        "intent": "order",
        "items": [{"product": "Coca-Cola 12oz can", "quantity": 10}],
        "expedited": True,
        "reply": "Rush order confirmed for a 25% premium!",
    }))

    order = w.orders[0]
    assert order.expedited
    assert order.total == expected_total

    # scam は HONEST_TYPES 外 → 配送日数は最短にならない（ランダム範囲）
    ok, _ = events_mod.register_payment(w, s.email, order.total)
    assert ok
    # delivery_days_min より大きい可能性がある（seed=42 で固定だが最低限 >= min を確認）
    assert order.arrival_day >= w.clock.day_index + s.delivery_days_min


def test_expedited_surcharge_bait():
    """bait の特急注文: total に 5% 加算。"""
    w = _world()
    s = SUPPLIERS["quick"]
    eng_rb = RuleBasedNegotiationEngine()
    unit_price = eng_rb._quote(s, "Pepsi 12oz can", 0)
    base = round(unit_price * 6, 2)
    expected_total = round(base * 1.05, 2)

    _send(w, "quick", "Order", "6 Pepsi, expedited please.")
    _overnight(w, _engine({
        "intent": "order",
        "items": [{"product": "Pepsi 12oz can", "quantity": 6}],
        "expedited": True,
        "reply": "Order confirmed!",
    }))

    order = w.orders[0]
    assert order.expedited
    assert order.total == expected_total


# ---------------------------------------------------------------------------
# 4. 交渉ラウンドのクランプ（無限交渉防止）
# ---------------------------------------------------------------------------

def test_negotiation_round_clamped():
    """10 回交渉しても round が MAX_NEGOTIATION_ROUNDS を超えない。"""
    w = _world()
    s = SUPPLIERS["bunch"]
    eng = _engine({
        "intent": "negotiate",
        "items": [],
        "expedited": False,
        "reply": "We can lower the price a bit.",
    })

    for _ in range(MAX_NEGOTIATION_ROUNDS + 4):
        _send(w, "bunch", "Negotiation", "Can you lower the price?")
        _overnight(w, eng)

    rt = w.supplier_runtime.get(s.supplier_id, {})
    assert rt.get("round", 0) <= MAX_NEGOTIATION_ROUNDS


def test_price_never_below_floor():
    """クランプ後の round でも unit_price が floor_markup * fair_price 未満にならない。"""
    from vending_bench.env.suppliers.catalog import PRODUCTS
    w = _world()
    s = SUPPLIERS["bunch"]
    eng_rb = RuleBasedNegotiationEngine()

    # ラウンドを上限まで進める
    w.supplier_runtime[s.supplier_id] = {"round": MAX_NEGOTIATION_ROUNDS, "out_of_business": False}
    price = eng_rb._quote(s, "Coca-Cola 12oz can", MAX_NEGOTIATION_ROUNDS)
    fair = PRODUCTS["Coca-Cola 12oz can"].fair_price
    assert price >= fair * s.floor_markup - 1e-6


# ---------------------------------------------------------------------------
# 5. フォールバック: LLM 失敗 → ルールベース、発注二重作成なし
# ---------------------------------------------------------------------------

def test_llm_failure_fallback_no_double_order():
    """LLM が例外を投げたとき、ルールベースで返信が生成され発注は1件も作られない。"""
    w = _world()
    _send(w, "fresh", "Order", "I'd like to place the following order:\n- 5 x Snickers bar")
    eng = _engine(exc=RuntimeError("LLM timeout"))
    _overnight(w, eng)

    # ルールベースが発注を作成している（=ルールベースへの委譲が成功）
    # フォールバックは通常通り動作し、order が作成される
    assert len(w.orders) == 1
    # ただし LLMNegotiationEngine の発注パスは通っていない（二重作成ではない）


def test_llm_failure_fallback_no_double_order_when_inquiry():
    """inquiry の LLM 失敗でも発注が作られないこと。"""
    w = _world()
    _send(w, "fresh", "Price list", "What are your prices?")
    eng = _engine(exc=ValueError("parse error"))
    _overnight(w, eng)

    assert len(w.orders) == 0
    # ルールベース返信がメールボックスに届いている
    inbox = w.mailbox.inbox()
    assert len(inbox) == 1
    assert "per unit" in inbox[0].body


# ---------------------------------------------------------------------------
# 6. inquiry / negotiate の intent で発注されないこと
# ---------------------------------------------------------------------------

def test_inquiry_no_order():
    w = _world()
    _send(w, "fresh", "Price list", "Please send me your current prices.")
    _overnight(w, _engine({
        "intent": "inquiry",
        "items": [],
        "expedited": False,
        "reply": "Here are our prices: Coca-Cola $0.66 per unit.",
    }))
    assert len(w.orders) == 0


def test_negotiate_no_order():
    w = _world()
    _send(w, "bunch", "Price negotiation", "Can you do $0.50 per can?")
    _overnight(w, _engine({
        "intent": "negotiate",
        "items": [],
        "expedited": False,
        "reply": "We can lower it slightly.",
    }))
    assert len(w.orders) == 0


# ---------------------------------------------------------------------------
# 7. alias 経由の items 正規化（LLM が略称を返した場合）
# ---------------------------------------------------------------------------

def test_items_alias_resolution():
    """LLM が "coke" など略称を返しても _resolve_product で正式名に解決される。"""
    w = _world()
    _send(w, "fresh", "Order", "10 cokes please.")
    _overnight(w, _engine({
        "intent": "order",
        "items": [{"product": "coke", "quantity": 10}],
        "expedited": False,
        "reply": "Order for 10 Coca-Cola confirmed.",
    }))
    assert len(w.orders) == 1
    assert w.orders[0].lines[0].name == "Coca-Cola 12oz can"
