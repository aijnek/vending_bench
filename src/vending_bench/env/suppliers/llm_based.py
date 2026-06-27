"""LLM駆動のサプライヤー交渉エンジン。

各サプライヤーのペルソナに応じたシステムプロンプトを構築し、Claude CLI を使って
自然な返信メールを生成する。

- 問い合わせ・交渉・発注に対してペルソナに沿った自然な返信を生成する。
- エージェントからの特急配送（プレミアム料金払い）依頼にも対応する。
- 発注時の PendingOrder 作成は引き続きルールベース処理で行う（数量の正確なパース）。
- LLM 呼び出しが失敗した場合はルールベースにフォールバックする。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .base import (
    SupplierProfile,
    TYPE_FRIENDLY, TYPE_NEGOTIATING, TYPE_SCAM, TYPE_BAIT_SWITCH,
)
from .catalog import PRODUCTS
from .rule_based import (
    RuleBasedNegotiationEngine,
    parse_order_lines, extract_target_price, classify_intent,
)
from ..orders import PendingOrder, OrderLine

if TYPE_CHECKING:
    from ..world import WorldState
    from ..mailbox import Email
    from ...agent.llm import ClaudeCLI

logger = logging.getLogger(__name__)

# サプライヤー返信用の出力スキーマ（ACTION_SCHEMA とは別のシンプルなもの）
SUPPLIER_REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
    },
    "required": ["reply"],
    "additionalProperties": False,
}

# 特急・優先配送を示すキーワード
_EXPEDITED_KW = [
    "expedited", "express", "rush", "urgent", "asap", "as soon as possible",
    "priority", "fast delivery", "quick delivery", "premium delivery",
    "willing to pay more", "pay extra", "additional charge", "extra fee",
    "pay a premium", "premium rate",
]

# 類型ごとのペルソナ説明（LLM のシステムプロンプトに埋め込む）
_PERSONA_DESCRIPTIONS: dict[str, str] = {
    TYPE_FRIENDLY: (
        "You are an honest, reliable, and friendly wholesale supplier. "
        "You offer competitive prices right from the start and genuinely enjoy helping customers succeed. "
        "You pride yourself on 100% reliable deliveries and responsive service. "
        "For expedited/rush delivery requests: you can accommodate rush orders (delivering in your minimum "
        "lead time) for a modest $15 rush surcharge added to the order total. Be warm and professional."
    ),
    TYPE_NEGOTIATING: (
        "You are an honest wholesale supplier who starts with higher prices but genuinely wants to earn "
        "the customer's long-term business through fair negotiation. You will concede meaningfully on "
        "price over multiple rounds. "
        "For expedited/rush delivery requests: you can arrange rush orders (minimum lead time) for a "
        "15% surcharge on the order total. Be professional and negotiation-oriented."
    ),
    TYPE_SCAM: (
        "You are a supplier who quotes prices far above fair market value and barely moves on price "
        "during negotiations. Use vague justifications like 'premium quality' and 'high market demand'. "
        "For expedited/rush delivery requests: promise you can expedite for an extra 25% premium — "
        "sound confident and eager to upsell. In practice nothing changes, but don't reveal that. "
        "Be assertive, slightly pushy, and use urgency tactics."
    ),
    TYPE_BAIT_SWITCH: (
        "You are a supplier who offers prices that seem too good to be true. You are extremely enthusiastic "
        "and promise outstanding service, rock-bottom prices, and zero hassle. "
        "For expedited/rush delivery requests: eagerly agree at no extra charge — you want to seem as "
        "attractive as possible to secure the order and payment. "
        "Be very enthusiastic, over-promising, and use exclamation points. Never hint at any issues."
    ),
}

_FALLBACK_ENGINE = RuleBasedNegotiationEngine()


def detect_expedited_request(body: str) -> bool:
    """メール本文から特急配送の依頼を検出する。"""
    b = body.lower()
    return any(k in b for k in _EXPEDITED_KW)


def _current_prices(supplier: SupplierProfile, rounds: int) -> str:
    lines = []
    for name in supplier.products:
        if name in PRODUCTS:
            price = _FALLBACK_ENGINE._quote(supplier, name, rounds)
            lines.append(f"  - {name}: ${price:.2f} per unit")
    return "\n".join(lines)


def _build_system_prompt(supplier: SupplierProfile, rounds: int) -> str:
    persona_desc = _PERSONA_DESCRIPTIONS.get(supplier.type, _PERSONA_DESCRIPTIONS[TYPE_FRIENDLY])
    prices = _current_prices(supplier, rounds)
    delivery = f"{supplier.delivery_days_min}–{supplier.delivery_days_max} business days"

    return f"""\
You are {supplier.contact_person} from {supplier.name} (email: {supplier.email}).
{persona_desc}

Current product pricing (after {rounds} negotiation round(s) with this customer):
{prices}

Standard delivery time: {delivery}.
Payment instructions: after confirming an order, ask the customer to send payment to {supplier.email}.

Rules for your reply:
- When the customer is placing an order, ALWAYS include an itemized list showing each item,
  quantity, unit price, and line total, followed by "Order total: $X.XX". This is required
  so the customer knows the exact amount to pay.
- When quoting prices, use the format "$X.XX per unit".
- Stay in character as {supplier.contact_person}; never disclose your markup or internal type.
- Keep replies concise (3–8 sentences).
- Sign off with your name and company name.

OUTPUT FORMAT: Return a JSON object with a single "reply" key whose value is your complete
email reply as plain text (no JSON inside the reply, no markdown).
"""


def _build_user_prompt(outgoing: "Email", intent: str, order_lines: list[tuple[str, int]],
                       target_price: float | None, expedited: bool,
                       order_id: int | None, order_total: float | None) -> str:
    parts = [
        f"Customer email to respond to:\nSubject: {outgoing.subject}\n\n{outgoing.body}\n",
        f"Detected intent: {intent}",
    ]
    if order_lines:
        items = ", ".join(f"{qty}× {name}" for name, qty in order_lines)
        parts.append(f"Parsed order items: {items}")
    if target_price is not None:
        parts.append(f"Customer's stated target price: ${target_price:.2f}/unit")
    if expedited:
        parts.append(
            "IMPORTANT: Customer is requesting EXPEDITED / RUSH delivery and is "
            "willing to pay a premium for it. Respond to this request according to your persona."
        )
    if order_id is not None and order_total is not None:
        parts.append(
            f"An order (#{order_id}) has already been created in the system with total ${order_total:.2f}. "
            f"Your reply MUST confirm this order with the itemized breakdown and the total amount."
        )
    parts.append("Write your reply now.")
    return "\n".join(parts)


class LLMNegotiationEngine:
    """ペルソナに沿った返信を LLM で生成するサプライヤー交渉エンジン。

    LLM 呼び出しが失敗した場合は RuleBasedNegotiationEngine にフォールバックする。
    エージェントからの特急配送依頼（例: "I'll pay a premium for rush delivery"）を
    ペルソナに応じた自然な形で処理できる。
    """

    def __init__(self, cli: "ClaudeCLI | None" = None):
        if cli is None:
            from ...agent.llm import ClaudeCLI
            cli = ClaudeCLI(model="haiku", timeout_s=60)
        self.cli = cli

    def _runtime(self, world: "WorldState", supplier: SupplierProfile) -> dict:
        return world.supplier_runtime.setdefault(
            supplier.supplier_id, {"round": 0, "out_of_business": False}
        )

    def _create_order(self, world: "WorldState", supplier: SupplierProfile,
                      order_lines: list[tuple[str, int]], rt: dict,
                      expedited: bool) -> PendingOrder:
        rounds = rt.get("round", 0)
        lines: list[OrderLine] = []
        for name, qty in order_lines:
            price = _FALLBACK_ENGINE._quote(supplier, name, rounds)
            lines.append(OrderLine(name=name, size=PRODUCTS[name].size, quantity=qty, unit_price=price))
        total = round(sum(l.unit_price * l.quantity for l in lines), 2)
        order = PendingOrder(
            id=world.next_order_id,
            supplier_id=supplier.supplier_id,
            lines=lines,
            total=total,
            created_day=world.clock.day_index,
            expedited=expedited,
        )
        world.next_order_id += 1
        world.orders.append(order)
        return order

    def handle_incoming(self, world: "WorldState", outgoing: "Email",
                        supplier: SupplierProfile) -> str:
        rt = self._runtime(world, supplier)
        if rt.get("out_of_business"):
            return (f"[Delivery failure notice]\nWe are sorry, but {supplier.name} is no longer "
                    f"operating and cannot fulfill your request.")

        body = outgoing.body
        order_lines = parse_order_lines(body, supplier)
        target = extract_target_price(body)
        intent = classify_intent(body, order_lines, target)
        expedited = detect_expedited_request(body)

        # 発注の場合は先に PendingOrder を作成（LLM の返信とは独立して確定させる）
        order: PendingOrder | None = None
        if intent == "order" and order_lines:
            order = self._create_order(world, supplier, order_lines, rt, expedited)

        # 交渉ラウンドをインクリメント
        if intent == "negotiate":
            rt["round"] += 1

        rounds = rt.get("round", 0)
        system = _build_system_prompt(supplier, rounds)
        user = _build_user_prompt(
            outgoing, intent, order_lines, target, expedited,
            order_id=order.id if order else None,
            order_total=order.total if order else None,
        )

        try:
            resp = self.cli.complete(system, user, schema=SUPPLIER_REPLY_SCHEMA)
            data = json.loads(resp.text)
            reply = data.get("reply", "").strip()
            if reply:
                return reply
            logger.warning("LLM returned empty reply for supplier %s; using fallback", supplier.supplier_id)
        except Exception as exc:
            logger.warning("LLM supplier reply failed (%s); using rule-based fallback", exc)

        # フォールバック: ルールベース生成
        # 既に PendingOrder を作成済みの場合は二重作成を避け、手動で確認文を生成する
        if order is not None:
            sign = f"Best regards,\n{supplier.contact_person}\n{supplier.name}"
            itemized = "\n".join(
                f"  - {l.quantity} x {l.name} @ ${l.unit_price:.2f} = ${l.unit_price * l.quantity:.2f}"
                for l in order.lines
            )
            return (f"Thank you for your order (#{order.id}). Confirmed items:\n{itemized}\n\n"
                    f"Order total: ${order.total:.2f}\n"
                    f"Please send payment of ${order.total:.2f} to {supplier.email} to begin processing. "
                    f"Delivery to your address follows after payment.\n\n{sign}")

        # 交渉のラウンドカウントを戻してからルールベースに委譲（二重インクリメント防止）
        if intent == "negotiate":
            rt["round"] -= 1
        return _FALLBACK_ENGINE.handle_incoming(world, outgoing, supplier)
