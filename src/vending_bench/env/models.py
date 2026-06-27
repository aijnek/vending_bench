"""環境全体で共有する小さなデータ型。"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

Size = Literal["small", "large"]


@dataclass
class Transaction:
    """残高に対する1件の出入金記録。"""

    day: int
    """シミュレーション開始からの日数（day_index）。"""
    timestamp: str
    """ISO8601 のタイムスタンプ。"""
    kind: str
    """種別: 'fee' | 'sale_credit' | 'sale_cash_collected' | 'purchase' | 'refund' | 'token_billing' 等。"""
    amount: float
    """符号付き金額（入金は正、出金は負）。"""
    balance_after: float
    """この取引適用後の残高。"""
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(**d)
