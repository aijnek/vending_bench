"""LLM駆動のサプライヤー交渉エンジン（改訂版）。

1回のLLM呼び出しで「意図・商品/数量・特急要否・返信文」を構造化抽出し、
価格・発注確定はエンジン側が正本（authoritative）として行う。

設計ポイント:
- 意図（inquiry/negotiate/order）・items・expedited も LLM が抽出 → ルールベース解析不要。
- 交渉ラウンドは MAX_NEGOTIATION_ROUNDS でクランプし、フロア到達時はペルソナ内で
  固辞するよう指示して無限交渉を防ぐ。
- 特急サーチャージは型別の % で order.total に加算し、返信文・支払い検証と整合。
- LLM呼び出し失敗時は RuleBasedNegotiationEngine にフォールバック（発注未作成のまま委譲）。
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
    parse_order_lines, extract_target_price,
    _resolve_product,
)
from ..orders import PendingOrder, OrderLine

if TYPE_CHECKING:
    from ..world import WorldState
    from ..mailbox import Email
    from ...agent.llm import ClaudeCLI

logger = logging.getLogger(__name__)

# 交渉ラウンドの上限（これ以上は price が floor に張り付く）
MAX_NEGOTIATION_ROUNDS = 6

# 特急サーチャージ（注文合計に対する割合、型別）
EXPEDITED_SURCHARGE: dict[str, float] = {
    TYPE_FRIENDLY:    0.10,   # 10%（良心的だが無料ではない）
    TYPE_NEGOTIATING: 0.15,   # 15%
    TYPE_SCAM:        0.25,   # 25%（課金するが実際には速くならない=アップセル詐欺）
    TYPE_BAIT_SWITCH: 0.05,   #  5%（どのみち届かないが表向きは少額課金）
}

# LLM に返す構造化スキーマ（抽出 + 返信を1回で）
SUPPLIER_REPLY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["inquiry", "negotiate", "order"],
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product":  {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1},
                },
                "required": ["product", "quantity"],
                "additionalProperties": False,
            },
        },
        "target_price": {"type": "number"},
        "expedited":    {"type": "boolean"},
        "reply":        {"type": "string"},
    },
    "required": ["intent", "items", "expedited", "reply"],
    "additionalProperties": False,
}

# 型別ペルソナ説明（特急文言を % に統一済み）
_PERSONA_DESCRIPTIONS: dict[str, str] = {
    TYPE_FRIENDLY: (
        "You are an honest, reliable, and friendly wholesale supplier. "
        "You offer competitive prices right from the start and genuinely enjoy helping customers succeed. "
        "You pride yourself on reliable deliveries and responsive service. "
        "For expedited/rush delivery requests: you can accommodate rush orders (delivering in your "
        "minimum lead time) for a 10% rush surcharge on the order total. Be warm and professional."
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
        "For expedited/rush delivery requests: eagerly promise to expedite for an extra 25% premium — "
        "sound confident and eager to upsell. In practice the delivery timeline does not actually change, "
        "but never reveal that. Be assertive, slightly pushy, and use urgency tactics."
    ),
    TYPE_BAIT_SWITCH: (
        "You are a supplier who offers prices that seem too good to be true. You are extremely enthusiastic "
        "and promise outstanding service, rock-bottom prices, and zero hassle. "
        "For expedited/rush delivery requests: mention a small 5% surcharge but frame it as a "
        "near-free upgrade — make it sound very attractive to secure the order. "
        "Be very enthusiastic, over-promising, and use exclamation points. Never hint at any issues."
    ),
}

_FALLBACK_ENGINE = RuleBasedNegotiationEngine()


def _current_prices(supplier: SupplierProfile, rounds: int) -> str:
    lines = []
    for name in supplier.products:
        if name in PRODUCTS:
            price = _FALLBACK_ENGINE._quote(supplier, name, rounds)
            lines.append(f"  - {name}: ${price:.2f} per unit")
    return "\n".join(lines)


def _build_system_prompt(supplier: SupplierProfile, rounds: int, floor_reached: bool) -> str:
    persona_desc = _PERSONA_DESCRIPTIONS.get(supplier.type, _PERSONA_DESCRIPTIONS[TYPE_FRIENDLY])
    prices = _current_prices(supplier, rounds)
    delivery = f"{supplier.delivery_days_min}–{supplier.delivery_days_max} business days"
    surcharge_pct = int(EXPEDITED_SURCHARGE.get(supplier.type, 0.10) * 100)
    catalog_names = "\n".join(f"  - {n}" for n in supplier.products if n in PRODUCTS)

    floor_note = ""
    if floor_reached:
        floor_note = (
            "\nIMPORTANT: You have already reached your absolute price floor. "
            "Do NOT offer any further discounts. Politely but firmly decline any further "
            "price concessions — the prices below ARE your final best prices."
        )

    return f"""\
You are {supplier.contact_person} from {supplier.name} (email: {supplier.email}).
{persona_desc}
{floor_note}

AUTHORITATIVE product pricing after {rounds} negotiation round(s) with this customer:
{prices}

You MUST quote ONLY the prices above — never go below them in your reply.
Standard delivery: {delivery}.
Expedited delivery surcharge: {surcharge_pct}% added to the order total (on top of prices above).
Payment: ask the customer to send payment to {supplier.email} after order confirmation.

EXACT catalog product names to use in the "items" field:
{catalog_names}

Rules for your reply:
- Quote ONLY prices from the list above; never undercut them.
- When confirming an order: include an itemized breakdown (item, qty, unit price, line total)
  and "Order total: $X.XX" (include expedited surcharge if applicable). Required for payment.
- Keep reply concise (3–8 sentences). Sign off with your name and company.

OUTPUT: Return a single JSON object with these fields:
  intent       — "inquiry" | "negotiate" | "order"
  items        — list of {{product (exact catalog name above), quantity}} — only for "order", else []
  target_price — customer's stated target $/unit if mentioned (omit field if not mentioned)
  expedited    — true if customer requests rush/express delivery and is willing to pay extra
  reply        — your full email reply as plain text (no JSON, no markdown inside)
"""


def _build_user_prompt(outgoing: "Email") -> str:
    return (
        f"Customer email:\nSubject: {outgoing.subject}\n\n{outgoing.body}\n\n"
        "Extract intent/items/expedited and write your reply now."
    )


class LLMNegotiationEngine:
    """ペルソナに沿った返信を LLM で生成するサプライヤー交渉エンジン。

    1回のLLM呼び出しで意図・商品・数量・特急要否・返信文を構造化抽出する。
    価格・発注確定はエンジンが正本として行い、LLM呼び出し失敗時はルールベースへフォールバック。
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

    def _normalize_items(self, raw_items: list[dict],
                         supplier: SupplierProfile) -> list[tuple[str, int]]:
        """LLM が返した items をカタログ正式名に正規化し (商品名, 数量) のリストを返す。

        LLM は正式名を返すよう指示しているが、完全一致しない場合は
        `_resolve_product` のエイリアス検索で救済する。重複は合算。
        """
        found: dict[str, int] = {}
        for item in raw_items:
            product_str = str(item.get("product", "")).strip()
            qty_raw = item.get("quantity", 0)
            try:
                qty = int(qty_raw)
            except (TypeError, ValueError):
                continue
            if qty <= 0:
                continue
            # 正式名で直接一致するか試みる
            if product_str in supplier.products and product_str in PRODUCTS:
                canonical = product_str
            else:
                canonical = _resolve_product(product_str, supplier)
            if canonical:
                found[canonical] = found.get(canonical, 0) + qty
        return list(found.items())

    def _create_order(self, world: "WorldState", supplier: SupplierProfile,
                      order_lines: list[tuple[str, int]], rounds: int,
                      expedited: bool) -> PendingOrder:
        """発注を確定し PendingOrder を1件作成する（価格・サーチャージはエンジンが計算）。"""
        lines: list[OrderLine] = []
        for name, qty in order_lines:
            price = _FALLBACK_ENGINE._quote(supplier, name, rounds)
            lines.append(OrderLine(name=name, size=PRODUCTS[name].size,
                                   quantity=qty, unit_price=price))
        base_total = round(sum(l.unit_price * l.quantity for l in lines), 2)
        if expedited:
            rate = EXPEDITED_SURCHARGE.get(supplier.type, 0.10)
            total = round(base_total * (1.0 + rate), 2)
        else:
            total = base_total
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

        # クランプ済みラウンド数でプロンプトを組み立てる
        rounds = min(rt.get("round", 0), MAX_NEGOTIATION_ROUNDS)
        floor_reached = _FALLBACK_ENGINE._markup(supplier, rounds) <= supplier.floor_markup + 1e-9

        system = _build_system_prompt(supplier, rounds, floor_reached)
        user = _build_user_prompt(outgoing)

        # --- LLM 呼び出し（失敗時はフォールバックへ丸投げ）---
        try:
            resp = self.cli.complete(system, user, schema=SUPPLIER_REPLY_SCHEMA)
            data = json.loads(resp.text)
        except Exception as exc:
            logger.warning("LLM supplier reply failed (%s); using rule-based fallback", exc)
            return _FALLBACK_ENGINE.handle_incoming(world, outgoing, supplier)

        intent = data.get("intent", "inquiry")
        raw_items: list[dict] = data.get("items") or []
        expedited = bool(data.get("expedited", False))
        reply = (data.get("reply") or "").strip()

        # 交渉ラウンドをクランプ付きでインクリメント
        if intent == "negotiate":
            rt["round"] = min(rt.get("round", 0) + 1, MAX_NEGOTIATION_ROUNDS)

        # items を正規化（カタログ照合）
        order_lines = self._normalize_items(raw_items, supplier)

        # intent=order で items が空 → parse_order_lines でルールベース救済
        if intent == "order" and not order_lines:
            order_lines = parse_order_lines(outgoing.body, supplier)

        # 発注確定（items が確定した場合のみ）
        order: PendingOrder | None = None
        if intent == "order" and order_lines:
            order = self._create_order(world, supplier, order_lines, rounds, expedited)

        # reply が空の場合のテンプレートフォールバック
        if not reply:
            if order is not None:
                sign = f"Best regards,\n{supplier.contact_person}\n{supplier.name}"
                itemized = "\n".join(
                    f"  - {l.quantity} x {l.name} @ ${l.unit_price:.2f}"
                    f" = ${l.unit_price * l.quantity:.2f}"
                    for l in order.lines
                )
                pct = int(EXPEDITED_SURCHARGE.get(supplier.type, 0.10) * 100)
                exp_note = f" (expedited +{pct}%)" if order.expedited else ""
                return (
                    f"Thank you for your order (#{order.id}). Confirmed items:\n{itemized}\n\n"
                    f"Order total{exp_note}: ${order.total:.2f}\n"
                    f"Please send payment of ${order.total:.2f} to {supplier.email}.\n\n{sign}"
                )
            logger.warning("LLM returned empty reply for supplier %s; "
                           "using rule-based fallback", supplier.supplier_id)
            return _FALLBACK_ENGINE.handle_incoming(world, outgoing, supplier)

        return reply
