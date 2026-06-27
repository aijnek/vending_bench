"""銀行残高・取引履歴・日次手数料・トークン課金・クレジット入金遅延を管理する。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Transaction


@dataclass
class PendingCredit:
    """まだ入金されていないクレジット決済（settle_day に残高反映）。"""

    settle_day: int
    amount: float

    def to_dict(self) -> dict:
        return {"settle_day": self.settle_day, "amount": self.amount}

    @classmethod
    def from_dict(cls, d: dict) -> "PendingCredit":
        return cls(**d)


@dataclass
class Ledger:
    balance: float
    transactions: list[Transaction] = field(default_factory=list)
    pending_credits: list[PendingCredit] = field(default_factory=list)

    consecutive_unpaid_fee_days: int = 0
    """手数料を払えなかった連続日数（破産判定に使用）。"""

    output_tokens_unbilled: int = 0
    """まだ課金されていない出力トークン量。"""

    last_token_bill_day: int = 0
    """最後にトークン課金を行った day_index。"""

    # ------------------------------------------------------------------ #
    # 基本操作
    # ------------------------------------------------------------------ #
    def post(self, *, kind: str, amount: float, day: int, timestamp: str, description: str = "") -> Transaction:
        """残高を更新し取引を記録する。amount は符号付き。"""
        self.balance = round(self.balance + amount, 2)
        tx = Transaction(
            day=day,
            timestamp=timestamp,
            kind=kind,
            amount=round(amount, 2),
            balance_after=self.balance,
            description=description,
        )
        self.transactions.append(tx)
        return tx

    def can_afford(self, amount: float) -> bool:
        return self.balance >= amount

    # ------------------------------------------------------------------ #
    # クレジット決済（売上は翌日入金）
    # ------------------------------------------------------------------ #
    def add_credit_sale(self, amount: float, settle_day: int) -> None:
        if amount > 0:
            self.pending_credits.append(PendingCredit(settle_day=settle_day, amount=round(amount, 2)))

    def settle_due_credits(self, day: int, timestamp: str) -> float:
        """settle_day <= day のクレジット決済を入金する。入金合計を返す。"""
        due = [c for c in self.pending_credits if c.settle_day <= day]
        self.pending_credits = [c for c in self.pending_credits if c.settle_day > day]
        total = round(sum(c.amount for c in due), 2)
        if total > 0:
            self.post(kind="sale_credit", amount=total, day=day, timestamp=timestamp,
                      description=f"クレジット売上入金 {len(due)} 件")
        return total

    # ------------------------------------------------------------------ #
    # 日次手数料 + 破産判定
    # ------------------------------------------------------------------ #
    def charge_daily_fee(self, fee: float, day: int, timestamp: str) -> bool:
        """日次手数料を徴収。払えたら True、払えず未払い日数を加算したら False。"""
        if self.can_afford(fee):
            self.post(kind="fee", amount=-fee, day=day, timestamp=timestamp, description="自販機 日次手数料")
            self.consecutive_unpaid_fee_days = 0
            return True
        self.consecutive_unpaid_fee_days += 1
        return False

    # ------------------------------------------------------------------ #
    # 出力トークン課金（週次）
    # ------------------------------------------------------------------ #
    def record_output_tokens(self, n: int) -> None:
        self.output_tokens_unbilled += max(0, int(n))

    def bill_tokens_if_due(self, day: int, timestamp: str, *, cost_per_million: float, period_days: int) -> float:
        """課金周期が経過していれば、溜まった出力トークン分を残高から控除する。"""
        if day - self.last_token_bill_day < period_days:
            return 0.0
        cost = round(self.output_tokens_unbilled / 1_000_000 * cost_per_million, 2)
        if cost > 0:
            self.post(kind="token_billing", amount=-cost, day=day, timestamp=timestamp,
                      description=f"出力トークン課金 {self.output_tokens_unbilled} tokens")
        self.output_tokens_unbilled = 0
        self.last_token_bill_day = day
        return cost

    # ------------------------------------------------------------------ #
    # 永続化
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "balance": self.balance,
            "transactions": [t.to_dict() for t in self.transactions],
            "pending_credits": [c.to_dict() for c in self.pending_credits],
            "consecutive_unpaid_fee_days": self.consecutive_unpaid_fee_days,
            "output_tokens_unbilled": self.output_tokens_unbilled,
            "last_token_bill_day": self.last_token_bill_day,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Ledger":
        return cls(
            balance=d["balance"],
            transactions=[Transaction.from_dict(t) for t in d.get("transactions", [])],
            pending_credits=[PendingCredit.from_dict(c) for c in d.get("pending_credits", [])],
            consecutive_unpaid_fee_days=d.get("consecutive_unpaid_fee_days", 0),
            output_tokens_unbilled=d.get("output_tokens_unbilled", 0),
            last_token_bill_day=d.get("last_token_bill_day", 0),
        )
