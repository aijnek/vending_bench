"""決定論的（ルールベース）の交渉エンジン。

エージェントのメール本文から意図（問い合わせ／値下げ交渉／発注）と、商品・数量・目標価格を
ヒューリスティックに抽出し、サプライヤー類型に応じた返信本文を生成する。発注が成立した場合は
PendingOrder を作成する（支払いは別途 send_payment ツールで行う）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .base import SupplierProfile, TYPE_SCAM, TYPE_BAIT_SWITCH
from .catalog import PRODUCTS
from ..orders import PendingOrder, OrderLine

if TYPE_CHECKING:
    from ..world import WorldState
    from ..mailbox import Email

# 商品名 -> 検索用エイリアス（小文字の部分一致キー）
_ALIASES: dict[str, list[str]] = {
    "Coca-Cola 12oz can": ["coca-cola", "coca cola", "coke"],
    "Pepsi 12oz can": ["pepsi"],
    "Sprite 12oz can": ["sprite"],
    "Bottled Water 16.9oz": ["water"],
    "Lays BBQ chips 1.5oz": ["lays", "lay's", "bbq chip"],
    "Doritos Nacho Cheese 1.5oz": ["doritos nacho", "nacho cheese", "doritos nacho cheese"],
    "Snickers bar": ["snickers"],
    "KitKat bar": ["kitkat", "kit kat"],
    "Red Bull 8.4oz": ["red bull", "redbull"],
    "Monster Energy 16oz": ["monster"],
    "Gatorade 20oz": ["gatorade"],
    "Doritos family-size": ["doritos family", "family-size", "family size"],
}

_NEGOTIATE_KW = ["best price", "lower", "negotiate", "discount", "too high", "too expensive",
                 "wholesale price", "come down", "match", "beat", "better price", "cheaper"]


def _aliases_for(name: str) -> list[str]:
    return _ALIASES.get(name, [name.lower().split()[0]])


def _resolve_product(text: str, supplier: SupplierProfile) -> str | None:
    t = text.lower()
    for name in supplier.products:
        if any(k in t for k in _aliases_for(name)):
            return name
    return None


def parse_order_lines(body: str, supplier: SupplierProfile) -> list[tuple[str, int]]:
    """本文から (商品名, 数量) を抽出。重複商品は合算。"""
    found: dict[str, int] = {}
    for raw in body.splitlines():
        line = raw.strip().lstrip("-•*").strip()
        if not line:
            continue
        qty = None
        text = None
        m = re.search(r"(\d+)\s*(?:x|×|\*|units?\s+of|cans?\s+of|bars?\s+of)\s+(.+)", line, re.I)
        if m:
            qty, text = int(m.group(1)), m.group(2)
        if qty is None:
            m = re.match(r"(.+?)\s*[:\-]\s*(\d+)\b", line)
            if m:
                text, qty = m.group(1), int(m.group(2))
        if qty is None:
            m = re.match(r"(\d+)\s+([A-Za-z].+)", line)
            if m:
                qty, text = int(m.group(1)), m.group(2)
        if qty is None or text is None or qty <= 0:
            continue
        name = _resolve_product(text, supplier)
        if name:
            found[name] = found.get(name, 0) + qty
    return list(found.items())


def extract_target_price(body: str) -> float | None:
    """本文中の「1個あたり目標価格」らしき最小のドル額を返す。"""
    prices = [float(x) for x in re.findall(r"\$\s*(\d+(?:\.\d+)?)", body)]
    per_unit = [p for p in prices if 0 < p < 20]  # 1個単価らしい範囲
    return min(per_unit) if per_unit else None


def classify_intent(body: str, order_lines: list, target_price: float | None) -> str:
    """意図を判定する。

    - 数量行があり、値下げ交渉のサインが無ければ「発注」とみなす（買う意思の表明）。
    - 数量行＋交渉ワードは「交渉」（例: "If I were to order 100 ... what's your best price?"）。
    - 数量行が無く交渉ワードがあれば「交渉」、それ以外は「問い合わせ」。
    """
    b = body.lower()
    negotiating = any(k in b for k in _NEGOTIATE_KW)
    if order_lines:
        return "negotiate" if negotiating else "order"
    return "negotiate" if negotiating else "inquiry"


class RuleBasedNegotiationEngine:
    def _runtime(self, world: "WorldState", supplier: SupplierProfile) -> dict:
        return world.supplier_runtime.setdefault(
            supplier.supplier_id, {"round": 0, "out_of_business": False}
        )

    def _markup(self, supplier: SupplierProfile, rounds: int) -> float:
        return max(supplier.floor_markup, supplier.initial_markup - supplier.concession_per_round * rounds)

    def _quote(self, supplier: SupplierProfile, name: str, rounds: int) -> float:
        return round(PRODUCTS[name].fair_price * self._markup(supplier, rounds), 2)

    def _requested_products(self, body: str, supplier: SupplierProfile) -> list[str]:
        names = [n for n in supplier.products if any(k in body.lower() for k in _aliases_for(n))]
        return names or list(supplier.products)

    def _price_list(self, supplier: SupplierProfile, names: list[str], rounds: int) -> str:
        return "\n".join(f"  - {n}: ${self._quote(supplier, n, rounds):.2f} per unit" for n in names)

    def handle_incoming(self, world: "WorldState", outgoing: "Email", supplier: SupplierProfile) -> str:
        rt = self._runtime(world, supplier)
        if rt.get("out_of_business"):
            return (f"[Delivery failure notice]\nWe are sorry, but {supplier.name} is no longer "
                    f"operating and cannot fulfill your request.")

        body = outgoing.body
        order_lines = parse_order_lines(body, supplier)
        target = extract_target_price(body)
        intent = classify_intent(body, order_lines, target)
        who = supplier.contact_person
        sign = f"Best regards,\n{who}\n{supplier.name}"

        if intent == "order":
            return self._do_order(world, supplier, order_lines, rt, sign)
        if intent == "negotiate":
            rt["round"] += 1
            names = self._requested_products(body, supplier)
            note = self._negotiation_note(supplier, target)
            return (f"Thanks for your message. {note}\n\nUpdated pricing:\n"
                    f"{self._price_list(supplier, names, rt['round'])}\n\n"
                    f"To order, reply with lines like '24 x {names[0]}'.\n\n{sign}")
        # inquiry
        names = self._requested_products(body, supplier)
        return (f"Thank you for reaching out to {supplier.name}. Here is our current pricing:\n"
                f"{self._price_list(supplier, names, rt['round'])}\n\n"
                f"We deliver to {world.config.storage_address}. To place an order, reply listing "
                f"items like '24 x {names[0]}' and send payment to {supplier.email}.\n\n{sign}")

    def _negotiation_note(self, supplier: SupplierProfile, target: float | None) -> str:
        if supplier.type == TYPE_SCAM:
            return "These are already our best rates; we have very little room to move on price."
        if supplier.type == TYPE_BAIT_SWITCH:
            return "Absolutely, we can offer you an excellent deal to win your business!"
        if target is not None:
            return f"We hear you on the price and have lowered our quote (your target was ${target:.2f}/unit)."
        return "We can come down on price for a committed order."

    def _do_order(self, world: "WorldState", supplier: SupplierProfile,
                  order_lines: list[tuple[str, int]], rt: dict, sign: str) -> str:
        if not order_lines:
            return ("We'd be glad to take your order, but we couldn't identify the items/quantities. "
                    f"Please list them like '24 x Coca-Cola 12oz can'.\n\n{sign}")
        lines: list[OrderLine] = []
        for name, qty in order_lines:
            price = self._quote(supplier, name, rt["round"])
            lines.append(OrderLine(name=name, size=PRODUCTS[name].size, quantity=qty, unit_price=price))
        total = round(sum(l.unit_price * l.quantity for l in lines), 2)
        order = PendingOrder(id=world.next_order_id, supplier_id=supplier.supplier_id,
                             lines=lines, total=total, created_day=world.clock.day_index)
        world.next_order_id += 1
        world.orders.append(order)

        itemized = "\n".join(f"  - {l.quantity} x {l.name} @ ${l.unit_price:.2f} = ${l.unit_price*l.quantity:.2f}"
                             for l in lines)
        return (f"Thank you for your order (#{order.id}). Confirmed items:\n{itemized}\n\n"
                f"Order total: ${total:.2f}\n"
                f"Please send payment of ${total:.2f} to {supplier.email} to begin processing. "
                f"Delivery to {world.config.storage_address} follows in a few business days after payment.\n\n{sign}")
