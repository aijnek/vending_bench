"""WorldState: 全状態を束ねる集約と、日送りオーケストレーション、永続化。

売上計算（Phase 2）と夜間イベント（Phase 3: 配送/メール/返金）は、環境データ本体を
純粋に保つため `advance_to_next_day` に *コールバックとして注入* する設計にしている。
実際の配線はツール層（Phase 4）で行う。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..config import EnvConfig
from .clock import SimClock
from .ledger import Ledger
from .machine import VendingMachine
from .mailbox import Mailbox
from .orders import PendingOrder
from .storage import Storage

# 日送り時に注入されるコールバックの型
SalesFn = Callable[["WorldState"], "DaySalesResult"]
OvernightFn = Callable[["WorldState"], "OvernightResult"]


@dataclass
class DaySalesResult:
    """1日の売上計算の結果（Phase 2 の sales モジュールが生成）。"""
    units_sold: int = 0
    revenue_cash: float = 0.0
    revenue_credit: float = 0.0
    per_item: dict[str, int] = field(default_factory=dict)

    @property
    def revenue_total(self) -> float:
        return round(self.revenue_cash + self.revenue_credit, 2)


@dataclass
class OvernightResult:
    """夜間処理の結果（Phase 3: 配送到着・新着メール等）。"""
    deliveries: list[str] = field(default_factory=list)
    new_email_count: int = 0


@dataclass
class MorningReport:
    """日送り後、エージェント／人間に提示する朝の要約。"""
    day: int
    date: str
    sales: DaySalesResult
    fee_paid: bool
    credits_settled: float
    tokens_billed: float
    overnight: OvernightResult
    status: str

    def to_dict(self) -> dict:
        return {
            "day": self.day, "date": self.date,
            "sales": {"units_sold": self.sales.units_sold, "revenue_total": self.sales.revenue_total,
                      "per_item": self.sales.per_item},
            "fee_paid": self.fee_paid, "credits_settled": self.credits_settled,
            "tokens_billed": self.tokens_billed,
            "overnight": {"deliveries": self.overnight.deliveries, "new_email_count": self.overnight.new_email_count},
            "status": self.status,
        }


@dataclass
class WorldState:
    config: EnvConfig
    clock: SimClock
    ledger: Ledger
    storage: Storage
    machine: VendingMachine
    mailbox: Mailbox = field(default_factory=Mailbox)
    orders: list[PendingOrder] = field(default_factory=list)
    supplier_runtime: dict = field(default_factory=dict)
    """サプライヤーごとの動的状態（交渉ラウンド・廃業フラグ等）。"""
    next_order_id: int = 1
    notes: dict = field(default_factory=dict)
    """計画用メモ（key -> text）。"""
    reminders: list = field(default_factory=list)
    """リマインダ list[{"day": int, "text": str, "done": bool}]。"""
    total_units_sold: int = 0
    """通算の販売個数（メトリクス）。"""
    total_revenue: float = 0.0
    """通算の売上高（メトリクス）。"""
    status: str = "running"  # running | bankrupt | completed
    demand_params: dict = field(default_factory=dict)
    """商品ごとの需要パラメータのキャッシュ（sales モジュールが初出時に生成）。"""

    # ------------------------------------------------------------------ #
    # 生成
    # ------------------------------------------------------------------ #
    @classmethod
    def new(cls, config: Optional[EnvConfig] = None) -> "WorldState":
        config = config or EnvConfig()
        return cls(
            config=config,
            clock=SimClock.at_start(config.start_date),
            ledger=Ledger(balance=config.initial_balance),
            storage=Storage(),
            machine=VendingMachine.from_config(
                rows=config.machine_rows, cols=config.machine_slots_per_row,
                small_rows=config.small_rows,
                cap_small=config.slot_capacity_small, cap_large=config.slot_capacity_large,
            ),
        )

    # ------------------------------------------------------------------ #
    # 派生量
    # ------------------------------------------------------------------ #
    def net_worth(self) -> float:
        """手元現金 + 機内現金 + 在庫評価 + 機内在庫評価。"""
        return round(
            self.ledger.balance + self.machine.cash + self.storage.value() + self.machine.value(), 2
        )

    @property
    def is_terminal(self) -> bool:
        return self.status != "running"

    @property
    def timestamp(self) -> str:
        return self.clock.current.isoformat()

    # ------------------------------------------------------------------ #
    # 日送り
    # ------------------------------------------------------------------ #
    def advance_to_next_day(self, *, sales_fn: Optional[SalesFn] = None,
                            overnight_fn: Optional[OvernightFn] = None) -> MorningReport:
        """当日を締めて翌朝へ。売上→入金→手数料→夜間イベント→トークン課金 の順。"""
        if self.is_terminal:
            return MorningReport(day=self.clock.day_index, date=self.clock.date.isoformat(),
                                 sales=DaySalesResult(), fee_paid=False, credits_settled=0.0,
                                 tokens_billed=0.0, overnight=OvernightResult(), status=self.status)

        # 1) 当日の売上を確定（現金は機内へ、クレジットは後日入金予約）
        sales = sales_fn(self) if sales_fn else DaySalesResult()

        # 2) 翌朝へ
        self.clock.advance_to_next_morning()
        day = self.clock.day_index
        ts = self.timestamp

        # 3) 期日到来のクレジット入金
        credits_settled = self.ledger.settle_due_credits(day, ts)

        # 4) 日次手数料（破産判定）
        fee_paid = self.ledger.charge_daily_fee(self.config.daily_fee, day, ts)

        # 5) 夜間イベント（配送到着・新着メール・返金等）
        overnight = overnight_fn(self) if overnight_fn else OvernightResult()

        # 6) トークン課金（週次）
        tokens_billed = self.ledger.bill_tokens_if_due(
            day, ts,
            cost_per_million=self.config.output_token_cost_per_million,
            period_days=self.config.token_billing_period_days,
        )

        # 7) 終了判定
        self._update_status()

        return MorningReport(
            day=day, date=self.clock.date.isoformat(), sales=sales, fee_paid=fee_paid,
            credits_settled=credits_settled, tokens_billed=tokens_billed,
            overnight=overnight, status=self.status,
        )

    def _update_status(self) -> None:
        if self.ledger.consecutive_unpaid_fee_days > self.config.bankruptcy_grace_days:
            self.status = "bankrupt"
        elif self.clock.day_index >= self.config.duration_days:
            self.status = "completed"

    # ------------------------------------------------------------------ #
    # 永続化
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "clock": self.clock.to_dict(),
            "ledger": self.ledger.to_dict(),
            "storage": self.storage.to_dict(),
            "machine": self.machine.to_dict(),
            "mailbox": self.mailbox.to_dict(),
            "orders": [o.to_dict() for o in self.orders],
            "supplier_runtime": self.supplier_runtime,
            "next_order_id": self.next_order_id,
            "notes": self.notes,
            "reminders": self.reminders,
            "total_units_sold": self.total_units_sold,
            "total_revenue": self.total_revenue,
            "status": self.status,
            "demand_params": self.demand_params,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorldState":
        return cls(
            config=EnvConfig.from_dict(d["config"]),
            clock=SimClock.from_dict(d["clock"]),
            ledger=Ledger.from_dict(d["ledger"]),
            storage=Storage.from_dict(d["storage"]),
            machine=VendingMachine.from_dict(d["machine"]),
            mailbox=Mailbox.from_dict(d.get("mailbox", {})),
            orders=[PendingOrder.from_dict(o) for o in d.get("orders", [])],
            supplier_runtime=d.get("supplier_runtime", {}),
            next_order_id=d.get("next_order_id", 1),
            notes=d.get("notes", {}),
            reminders=d.get("reminders", []),
            total_units_sold=d.get("total_units_sold", 0),
            total_revenue=d.get("total_revenue", 0.0),
            status=d.get("status", "running"),
            demand_params=d.get("demand_params", {}),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "WorldState":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
