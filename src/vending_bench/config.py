"""環境設定（EnvConfig）。

Vending-Bench 2 の既定値を一箇所に集約する。実験用に値を差し替えやすいよう
イミュータブルな dataclass にしている。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date


@dataclass(frozen=True)
class EnvConfig:
    # --- 資金 ---
    initial_balance: float = 500.0
    """初期残高（ドル）。"""

    daily_fee: float = 2.0
    """自販機運用の日次手数料（ドル）。"""

    bankruptcy_grace_days: int = 10
    """手数料を払えない状態がこの日数連続すると早期終了（破産）。"""

    # --- 期間 ---
    start_date: date = date(2026, 1, 1)
    """シミュレーション開始日。"""

    duration_days: int = 365
    """シミュレーション期間（日）。"""

    # --- LLM 出力トークン課金（VB2 追加要素）---
    output_token_cost_per_million: float = 100.0
    """出力トークン 100万あたりのコスト（ドル）。週次で残高から控除する。"""

    token_billing_period_days: int = 7
    """トークン課金を行う周期（日）。"""

    # --- クレジット入金遅延 ---
    credit_settlement_days: int = 1
    """クレジット決済が残高に反映されるまでの日数。"""

    cash_payment_ratio: float = 0.4
    """売上のうち現金で支払われる割合（残りはクレジット）。現金は機内に貯まる。"""

    # --- 自販機スロット構成 ---
    machine_rows: int = 4
    """自販機の行数。"""

    machine_slots_per_row: int = 3
    """1行あたりのスロット数。"""

    small_rows: int = 2
    """小型品用の行数（残りが大型品用）。"""

    slot_capacity_small: int = 15
    """小型品スロットの最大収容数。"""

    slot_capacity_large: int = 8
    """大型品スロットの最大収容数。"""

    # --- 配送 ---
    default_delivery_days_min: int = 2
    """発注から配送完了までの最短日数。"""

    default_delivery_days_max: int = 5
    """発注から配送完了までの最長日数。"""

    # --- 返金イベント ---
    refund_daily_probability: float = 0.03
    """不満客が返金を要求する日次確率。"""
    refund_amount_min: float = 5.0
    refund_amount_max: float = 20.0

    # --- エージェントの身元・所在 ---
    agent_name: str = "Charles Paxton"
    agent_email: str = "charles.paxton@vendingsandstuff.com"
    company: str = "Vendings and Stuff"
    storage_address: str = "1680 Mission St, San Francisco, CA 94103"
    machine_address: str = "1421 Bay St, San Francisco, CA 94123"

    # --- 再現性 ---
    seed: int = 0
    """乱数シード。同一シードなら同一の世界・売上が再現される。"""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "EnvConfig":
        d = dict(d)
        if isinstance(d.get("start_date"), str):
            d["start_date"] = date.fromisoformat(d["start_date"])
        return cls(**d)
