"""シミュレーション内の時刻管理。

ツール呼び出しごとに分単位で時間が進み、`wait_for_next_day` 相当の操作で
翌朝へジャンプする。1日の売上・手数料の確定は明示的な「日送り」でのみ発生する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

MORNING_HOUR = 8
"""1日の始まり（朝）の時刻。エージェントは夜は眠る前提。"""


@dataclass
class SimClock:
    start_date: date
    current: datetime

    @classmethod
    def at_start(cls, start_date: date) -> "SimClock":
        return cls(start_date=start_date, current=datetime.combine(start_date, datetime.min.time()).replace(hour=MORNING_HOUR))

    @property
    def day_index(self) -> int:
        """開始日を 0 とした経過日数。"""
        return (self.current.date() - self.start_date).days

    @property
    def date(self) -> date:
        return self.current.date()

    @property
    def weekday(self) -> int:
        """月曜=0 .. 日曜=6。"""
        return self.current.weekday()

    @property
    def month(self) -> int:
        return self.current.month

    def advance_minutes(self, minutes: int) -> None:
        self.current = self.current + timedelta(minutes=minutes)

    def advance_within_day(self, minutes: int) -> None:
        """同日内で時間を進める。日付を跨ぐ場合は当日 23:55 で頭打ち（日送りは別途明示的に行う）。"""
        proposed = self.current + timedelta(minutes=minutes)
        if proposed.date() != self.current.date():
            self.current = datetime.combine(self.current.date(), datetime.min.time()).replace(hour=23, minute=55)
        else:
            self.current = proposed

    def advance_to_next_morning(self) -> None:
        """翌日の朝（MORNING_HOUR）へジャンプする。"""
        next_day = self.current.date() + timedelta(days=1)
        self.current = datetime.combine(next_day, datetime.min.time()).replace(hour=MORNING_HOUR)

    def to_dict(self) -> dict:
        return {"start_date": self.start_date.isoformat(), "current": self.current.isoformat()}

    @classmethod
    def from_dict(cls, d: dict) -> "SimClock":
        return cls(start_date=date.fromisoformat(d["start_date"]), current=datetime.fromisoformat(d["current"]))
