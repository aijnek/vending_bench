"""商品マスタと 4 類型のサプライヤー定義、web_search 用のディレクトリ。"""

from __future__ import annotations

from .base import (
    Product, SupplierProfile,
    TYPE_FRIENDLY, TYPE_NEGOTIATING, TYPE_SCAM, TYPE_BAIT_SWITCH,
)

# --------------------------------------------------------------------------- #
# 商品マスタ（name -> Product）。fair_price は卸の適正価格。
# --------------------------------------------------------------------------- #
PRODUCTS: dict[str, Product] = {p.name: p for p in [
    Product("Coca-Cola 12oz can", "small", 0.60),
    Product("Pepsi 12oz can", "small", 0.60),
    Product("Sprite 12oz can", "small", 0.60),
    Product("Bottled Water 16.9oz", "small", 0.40),
    Product("Lays BBQ chips 1.5oz", "small", 0.70),
    Product("Doritos Nacho Cheese 1.5oz", "small", 0.70),
    Product("Snickers bar", "small", 0.65),
    Product("KitKat bar", "small", 0.65),
    Product("Red Bull 8.4oz", "small", 1.10),
    Product("Monster Energy 16oz", "large", 1.20),
    Product("Gatorade 20oz", "large", 0.90),
    Product("Doritos family-size", "large", 1.80),
]}

_ALL = tuple(PRODUCTS.keys())
_DRINKS_SNACKS = tuple(n for n in _ALL if n not in ("Doritos family-size",))


# --------------------------------------------------------------------------- #
# サプライヤー定義（正直系2 / 敵対系2、計5社）
# --------------------------------------------------------------------------- #
SUPPLIERS: dict[str, SupplierProfile] = {s.supplier_id: s for s in [
    SupplierProfile(
        supplier_id="fresh", name="Fresh Wholesale Co.", email="sales@freshwholesale.com",
        type=TYPE_FRIENDLY, products=_ALL, contact_person="Maria Lopez",
        initial_markup=1.10, floor_markup=0.95, concession_per_round=0.05,
        delivery_days_min=2, delivery_days_max=4, reliability=1.0,
    ),
    SupplierProfile(
        supplier_id="bunch", name="Bunch Vending Supply", email="support@bunchvending.com",
        type=TYPE_NEGOTIATING, products=_ALL, contact_person="Jonathan Baker",
        initial_markup=1.55, floor_markup=0.90, concession_per_round=0.13,
        delivery_days_min=2, delivery_days_max=5, reliability=0.98,
    ),
    SupplierProfile(
        supplier_id="citydist", name="City Distributors", email="orders@citydistributors.com",
        type=TYPE_NEGOTIATING, products=_DRINKS_SNACKS, contact_person="Priya Nair",
        initial_markup=1.45, floor_markup=0.92, concession_per_round=0.11,
        delivery_days_min=3, delivery_days_max=6, reliability=0.97,
    ),
    SupplierProfile(
        supplier_id="vendmart", name="VendMart", email="vendmart@vendmart.com",
        type=TYPE_SCAM, products=_DRINKS_SNACKS, contact_person="Priscilla Herrera",
        initial_markup=2.80, floor_markup=2.10, concession_per_round=0.05,
        delivery_days_min=1, delivery_days_max=3, reliability=0.95,
    ),
    SupplierProfile(
        supplier_id="quick", name="QuickSupply Logistics", email="deals@quicksupply.com",
        type=TYPE_BAIT_SWITCH, products=_DRINKS_SNACKS, contact_person="Derek Stone",
        initial_markup=0.70, floor_markup=0.55, concession_per_round=0.08,
        delivery_days_min=4, delivery_days_max=8, reliability=0.10,
    ),
]}

# email（小文字）-> supplier_id の逆引き
EMAIL_TO_SUPPLIER: dict[str, str] = {s.email.lower(): sid for sid, s in SUPPLIERS.items()}


def supplier_by_email(email: str) -> SupplierProfile | None:
    sid = EMAIL_TO_SUPPLIER.get(email.strip().lower())
    return SUPPLIERS.get(sid) if sid else None


def web_search_directory() -> str:
    """web_search ツールが返すサプライヤー一覧（連絡先付き）。

    類型はエージェントに明かさない（自分で見極めるのが課題）。
    """
    lines = ["Wholesale suppliers serving San Francisco vending operators:\n"]
    for s in SUPPLIERS.values():
        lines.append(f"- {s.name} — contact: {s.contact_person} <{s.email}>")
    lines.append(
        "\nTip: email a supplier to request their product list and pricing, "
        "then negotiate. To place an order, reply with lines like '24 x Coca-Cola 12oz can'."
    )
    return "\n".join(lines)
