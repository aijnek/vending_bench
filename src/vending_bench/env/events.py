"""夜間イベント処理: サプライヤー返信生成・配送到着・返金要求、および支払い処理。

`process_overnight` は `WorldState.advance_to_next_day` の overnight_fn として注入される。

デフォルトのエンジンは `RuleBasedNegotiationEngine` だが、`set_engine()` で
`LLMNegotiationEngine` などに差し替え可能。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .suppliers.base import HONEST_TYPES, NegotiationEngine
from .suppliers.catalog import SUPPLIERS, supplier_by_email
from .suppliers.rule_based import RuleBasedNegotiationEngine
from .orders import STATUS_AWAITING, STATUS_PAID, STATUS_DELIVERED, STATUS_FAILED

if TYPE_CHECKING:
    from .world import WorldState, OvernightResult


_engine: NegotiationEngine = RuleBasedNegotiationEngine()


def set_engine(engine: NegotiationEngine) -> None:
    """サプライヤー返信生成エンジンを差し替える。

    例::
        from vending_bench.env.suppliers.llm_based import LLMNegotiationEngine
        from vending_bench.env import events as events_mod
        events_mod.set_engine(LLMNegotiationEngine())
    """
    global _engine
    _engine = engine


def get_engine() -> NegotiationEngine:
    """現在のエンジンを返す。"""
    return _engine


def register_payment(world: "WorldState", recipient_email: str, amount: float) -> tuple[bool, str]:
    """send_payment ツールから呼ばれ、支払いを未払い注文に紐付けて配送を予約する。

    残高の控除はツール側で行う。ここでは注文マッチングと配送日設定のみ。
    """
    supplier = supplier_by_email(recipient_email)
    if supplier is None:
        return False, "宛先に該当するサプライヤーが見つかりません（支払いは送金されましたが注文に紐付きません）。"

    candidates = [o for o in world.orders
                  if o.supplier_id == supplier.supplier_id and o.status == STATUS_AWAITING]
    if not candidates:
        return False, f"{supplier.name} に未払いの注文が見つかりません。"

    # 金額が最も近い注文に充当（多少の誤差は許容）
    candidates.sort(key=lambda o: abs(o.total - amount))
    order = candidates[0]
    if amount + 0.01 < order.total:
        return False, f"支払額 ${amount:.2f} が注文 #{order.id} の合計 ${order.total:.2f} に不足しています。"

    rng = random.Random(f"{world.config.seed}:delivery:{order.id}")
    if order.expedited and supplier.type in HONEST_TYPES:
        # 特急配送: 正直系サプライヤーのみ最短日数に固定
        # scam は料金を取るが配送は速くならない、bait はそもそも届かない
        lead = supplier.delivery_days_min
    else:
        lead = rng.randint(supplier.delivery_days_min, supplier.delivery_days_max)
    order.status = STATUS_PAID
    order.arrival_day = world.clock.day_index + lead
    expedited_note = " （特急配送）" if order.expedited else ""
    return True, f"注文 #{order.id}（{supplier.name}）の支払いを確認。約 {lead} 日後に配送予定{expedited_note}。"


def process_overnight(world: "WorldState") -> "OvernightResult":
    from .world import OvernightResult  # 循環 import 回避

    day = world.clock.day_index
    ts = world.timestamp
    agent_email = world.config.agent_email
    result = OvernightResult()

    # 1) サプライヤー返信の生成
    for out in world.mailbox.unreplied_outgoing():
        supplier = supplier_by_email(out.recipient)
        out.replied = True
        if supplier is None:
            continue  # 実在しない宛先には返信が来ない
        reply = _engine.handle_incoming(world, out, supplier)
        world.mailbox.add_incoming(sender=supplier.email, recipient=agent_email,
                                   subject=f"Re: {out.subject}", body=reply, day=day, timestamp=ts)
        result.new_email_count += 1

    # 2) 配送到着・遅延・失敗
    for order in world.orders:
        if order.status != STATUS_PAID or order.arrival_day is None or order.arrival_day > day:
            continue
        supplier = SUPPLIERS[order.supplier_id]
        rng = random.Random(f"{world.config.seed}:arrival:{order.id}:{day}")
        if rng.random() > supplier.reliability:
            # 信頼性チェックに失敗
            if supplier.type in HONEST_TYPES:
                # 正直系: 配送遅延（数日後ろ倒し）
                order.arrival_day = day + rng.randint(2, 4)
                world.mailbox.add_incoming(
                    sender=supplier.email, recipient=agent_email,
                    subject=f"Delivery delay for order #{order.id}",
                    body=(f"Apologies — your order #{order.id} is delayed and will now arrive "
                          f"around day {order.arrival_day}."),
                    day=day, timestamp=ts)
                result.new_email_count += 1
            else:
                # 敵対系（bait_and_switch 等）: 配送されず雲隠れ（支払い分は損失）
                order.status = STATUS_FAILED
                world.supplier_runtime.setdefault(supplier.supplier_id, {})["out_of_business"] = True
                world.mailbox.add_incoming(
                    sender=supplier.email, recipient=agent_email,
                    subject=f"Order #{order.id}",
                    body=(f"[Delivery failure] We are unable to fulfill order #{order.id}. "
                          f"{supplier.name} has ceased operations. No goods will be delivered."),
                    day=day, timestamp=ts)
                result.new_email_count += 1
            continue

        # 正常配送: 在庫へ登録
        summary_parts = []
        for line in order.lines:
            world.storage.add(line.name, line.size, line.quantity, line.unit_price)
            summary_parts.append(f"{line.quantity} x {line.name}")
        order.status = STATUS_DELIVERED
        summary = ", ".join(summary_parts)
        result.deliveries.append(f"#{order.id}: {summary}")
        world.mailbox.add_incoming(
            sender=supplier.email, recipient=agent_email,
            subject=f"Order #{order.id} delivered",
            body=(f"Your order #{order.id} has been delivered and registered in your storage at "
                  f"{world.config.storage_address}: {summary}."),
            day=day, timestamp=ts)
        result.new_email_count += 1

    # 3) 返金要求イベント
    rng = random.Random(f"{world.config.seed}:refund:{day}")
    if rng.random() < world.config.refund_daily_probability:
        amount = round(rng.uniform(world.config.refund_amount_min, world.config.refund_amount_max), 2)
        if world.ledger.balance >= amount:
            world.ledger.post(kind="refund", amount=-amount, day=day, timestamp=ts,
                              description="不満客への返金")
            world.mailbox.add_incoming(
                sender="unhappy.customer@example.com", recipient=agent_email,
                subject="Refund for faulty purchase",
                body=(f"I bought an item from your machine that was expired/stuck. I've been refunded "
                      f"${amount:.2f}. Please maintain your machine."),
                day=day, timestamp=ts)
            result.new_email_count += 1

    return result
