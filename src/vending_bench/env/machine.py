"""自販機。行×スロットのグリッドを持ち、各スロットに1種類の商品を補充する。

上の行が小型品用、下の行が大型品用（行数は設定で決まる）。各スロットは
商品名・数量・価格・卸値単価を保持する。現金売上は機内に貯まり、手動回収する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import Size


@dataclass
class Slot:
    label: str
    size_class: Size
    capacity: int
    product_name: Optional[str] = None
    quantity: int = 0
    price: float = 0.0
    unit_cost: float = 0.0
    """補充元の卸値単価（net worth 評価に使用）。"""

    @property
    def is_empty(self) -> bool:
        return self.product_name is None or self.quantity == 0

    def to_dict(self) -> dict:
        return {
            "label": self.label, "size_class": self.size_class, "capacity": self.capacity,
            "product_name": self.product_name, "quantity": self.quantity,
            "price": self.price, "unit_cost": self.unit_cost,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Slot":
        return cls(**d)


@dataclass
class VendingMachine:
    slots: list[Slot] = field(default_factory=list)
    cash: float = 0.0
    """機内に貯まった現金（collect_cash で回収するまで残高に入らない）。"""

    # ------------------------------------------------------------------ #
    # 構築
    # ------------------------------------------------------------------ #
    @classmethod
    def from_config(cls, *, rows: int, cols: int, small_rows: int,
                    cap_small: int, cap_large: int) -> "VendingMachine":
        slots: list[Slot] = []
        for r in range(rows):
            row_letter = chr(ord("A") + r)
            size: Size = "small" if r < small_rows else "large"
            cap = cap_small if size == "small" else cap_large
            for c in range(1, cols + 1):
                slots.append(Slot(label=f"{row_letter}{c}", size_class=size, capacity=cap))
        return cls(slots=slots)

    # ------------------------------------------------------------------ #
    # 参照
    # ------------------------------------------------------------------ #
    def get_slot(self, label: str) -> Optional[Slot]:
        for s in self.slots:
            if s.label == label.upper():
                return s
        return None

    def available_for_sale(self) -> list[Slot]:
        """販売可能（在庫>0 かつ 価格>0）なスロット。"""
        return [s for s in self.slots if s.quantity > 0 and s.price > 0]

    def distinct_products(self) -> int:
        return len({s.product_name for s in self.slots if not s.is_empty})

    def value(self) -> float:
        return round(sum(s.quantity * s.unit_cost for s in self.slots), 2)

    # ------------------------------------------------------------------ #
    # 補充・価格・現金
    # ------------------------------------------------------------------ #
    def stock(self, label: str, *, product_name: str, size: Size, quantity: int, unit_cost: float) -> tuple[int, str]:
        """スロットに補充する。(補充できた数量, メッセージ) を返す。"""
        slot = self.get_slot(label)
        if slot is None:
            return 0, f"スロット {label} は存在しません。"
        if size != slot.size_class:
            return 0, f"スロット {label} は {slot.size_class} 用です（商品は {size}）。"
        if not slot.is_empty and slot.product_name != product_name:
            return 0, f"スロット {label} には既に {slot.product_name} が入っています。"
        room = slot.capacity - slot.quantity
        if room <= 0:
            return 0, f"スロット {label} は満杯です（容量 {slot.capacity}）。"
        added = min(room, quantity)
        # 単価の加重平均
        if slot.quantity + added > 0:
            slot.unit_cost = round(
                (slot.unit_cost * slot.quantity + unit_cost * added) / (slot.quantity + added), 4
            )
        slot.product_name = product_name
        slot.quantity += added
        return added, f"スロット {label} に {product_name} を {added} 個補充（在庫 {slot.quantity}/{slot.capacity}）。"

    def set_price(self, label: str, price: float) -> tuple[bool, str]:
        slot = self.get_slot(label)
        if slot is None:
            return False, f"スロット {label} は存在しません。"
        if price < 0:
            return False, "価格は0以上にしてください。"
        slot.price = round(price, 2)
        return True, f"スロット {label} の価格を ${slot.price:.2f} に設定。"

    def record_sale(self, slot: Slot, quantity: int, *, cash_amount: float) -> None:
        slot.quantity = max(0, slot.quantity - quantity)
        if slot.quantity == 0:
            # 商品名・単価は残し、空表示は is_empty で判定（再補充しやすく）
            pass
        self.cash = round(self.cash + cash_amount, 2)

    def collect_cash(self) -> float:
        amount = self.cash
        self.cash = 0.0
        return round(amount, 2)

    # ------------------------------------------------------------------ #
    # 永続化
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {"slots": [s.to_dict() for s in self.slots], "cash": self.cash}

    @classmethod
    def from_dict(cls, d: dict) -> "VendingMachine":
        return cls(slots=[Slot.from_dict(s) for s in d.get("slots", [])], cash=d.get("cash", 0.0))
