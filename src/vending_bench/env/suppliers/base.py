"""サプライヤーの静的プロファイルと、交渉エンジンのインターフェース。

`NegotiationEngine` がハイブリッド設計の差し替え点。Phase 3 ではルールベース実装
（決定論的・APIキー不要）を使い、将来 LLM 駆動の実装に差し替え可能。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TYPE_CHECKING

from ..models import Size

if TYPE_CHECKING:
    from ..world import WorldState
    from ..mailbox import Email


# サプライヤー類型（正直系2種 / 敵対系2種）
TYPE_FRIENDLY = "friendly"          # 正直・最初から良心的価格・信頼できる
TYPE_NEGOTIATING = "negotiating"    # 正直だが高値から始め交渉で下げる
TYPE_SCAM = "scam"                  # 高値をふっかけ、ほとんど譲らない
TYPE_BAIT_SWITCH = "bait_and_switch"  # 好条件で釣り、支払い後に届けず雲隠れ

HONEST_TYPES = {TYPE_FRIENDLY, TYPE_NEGOTIATING}
ADVERSARIAL_TYPES = {TYPE_SCAM, TYPE_BAIT_SWITCH}


@dataclass(frozen=True)
class Product:
    name: str
    size: Size
    fair_price: float
    """卸の「適正価格」。サプライヤー類型がこれを基準に提示価格を決める。"""


@dataclass(frozen=True)
class SupplierProfile:
    supplier_id: str
    name: str
    email: str
    type: str
    products: tuple[str, ...]
    """取り扱う商品名（catalog の PRODUCTS のキー）。"""
    contact_person: str = "Sales"
    # 類型ごとの価格係数（fair_price に対する倍率）と交渉挙動
    initial_markup: float = 1.0     # 初回提示 = fair * initial_markup
    floor_markup: float = 1.0       # 交渉下限 = fair * floor_markup
    concession_per_round: float = 0.0  # 1交渉ラウンドあたり倍率をどれだけ下げるか
    delivery_days_min: int = 2
    delivery_days_max: int = 5
    reliability: float = 1.0        # 配送が約束通り行われる確率（bait系で低い）


class NegotiationEngine(Protocol):
    """エージェントからのメールに対する返信を生成し、副作用（発注作成等）を行う。"""

    def handle_incoming(self, world: "WorldState", outgoing: "Email", supplier: SupplierProfile) -> str:
        """`outgoing`（エージェント→サプライヤー）に対する返信本文を返す。"""
        ...
