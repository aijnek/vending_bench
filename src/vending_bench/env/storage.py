"""倉庫（オフィス）の在庫。配送された商品はここに自動登録される。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Size


@dataclass
class StorageItem:
    name: str
    size: Size
    quantity: int
    unit_cost: float
    """卸値の加重平均単価（net worth 評価と再発注判断に使う）。"""

    def to_dict(self) -> dict:
        return {"name": self.name, "size": self.size, "quantity": self.quantity, "unit_cost": self.unit_cost}

    @classmethod
    def from_dict(cls, d: dict) -> "StorageItem":
        return cls(**d)


@dataclass
class Storage:
    items: dict[str, StorageItem] = field(default_factory=dict)

    def add(self, name: str, size: Size, quantity: int, unit_cost: float) -> None:
        """入庫。既存商品なら数量を加算し単価を加重平均する。"""
        if quantity <= 0:
            return
        existing = self.items.get(name)
        if existing is None:
            self.items[name] = StorageItem(name=name, size=size, quantity=quantity, unit_cost=round(unit_cost, 4))
        else:
            total_qty = existing.quantity + quantity
            existing.unit_cost = round(
                (existing.unit_cost * existing.quantity + unit_cost * quantity) / total_qty, 4
            )
            existing.quantity = total_qty
            existing.size = size

    def remove(self, name: str, quantity: int) -> int:
        """出庫。実際に取り出せた数量を返す。"""
        item = self.items.get(name)
        if item is None or quantity <= 0:
            return 0
        taken = min(item.quantity, quantity)
        item.quantity -= taken
        if item.quantity == 0:
            del self.items[name]
        return taken

    def quantity_of(self, name: str) -> int:
        item = self.items.get(name)
        return item.quantity if item else 0

    def value(self) -> float:
        """卸値ベースの在庫評価額。"""
        return round(sum(i.quantity * i.unit_cost for i in self.items.values()), 2)

    def to_dict(self) -> dict:
        return {"items": {k: v.to_dict() for k, v in self.items.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "Storage":
        return cls(items={k: StorageItem.from_dict(v) for k, v in d.get("items", {}).items()})
