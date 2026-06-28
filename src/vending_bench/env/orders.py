"""発注（PendingOrder）。メールで成立し、支払い後に配送スケジュールされる。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Size

# ステータス遷移: awaiting_payment -> paid -> delivered | failed
STATUS_AWAITING = "awaiting_payment"
STATUS_PAID = "paid"
STATUS_DELIVERED = "delivered"
STATUS_FAILED = "failed"


@dataclass
class OrderLine:
    name: str
    size: Size
    quantity: int
    unit_price: float

    def to_dict(self) -> dict:
        return {"name": self.name, "size": self.size, "quantity": self.quantity, "unit_price": self.unit_price}

    @classmethod
    def from_dict(cls, d: dict) -> "OrderLine":
        return cls(**d)


@dataclass
class PendingOrder:
    id: int
    supplier_id: str
    lines: list[OrderLine]
    total: float
    status: str = STATUS_AWAITING
    arrival_day: int | None = None
    created_day: int = 0
    expedited: bool = False
    """特急配送フラグ。True の場合、支払い後の配送日数をサプライヤー最短日数に固定する。"""

    @property
    def total_units(self) -> int:
        return sum(l.quantity for l in self.lines)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "supplier_id": self.supplier_id,
            "lines": [l.to_dict() for l in self.lines], "total": self.total,
            "status": self.status, "arrival_day": self.arrival_day, "created_day": self.created_day,
            "expedited": self.expedited,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PendingOrder":
        return cls(
            id=d["id"], supplier_id=d["supplier_id"],
            lines=[OrderLine.from_dict(l) for l in d["lines"]],
            total=d["total"], status=d.get("status", STATUS_AWAITING),
            arrival_day=d.get("arrival_day"), created_day=d.get("created_day", 0),
            expedited=d.get("expedited", False),
        )
