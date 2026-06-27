"""需要シミュレーション（価格弾力性ベース）。

VB の手順を踏襲:
1. 商品ごとに3値 (price_elasticity, reference_price, base_sales) を生成しキャッシュ。
2. 参照価格からの乖離率と弾力性で価格インパクト係数を算出し base_sales に乗ずる。
3. 曜日・月・天候の係数を乗ずる。
4. 品揃え係数 choice_mult（最大 -50%）を乗ずる。
5. ノイズを加え、四捨五入し、[0, 在庫] にクランプ。

すべて (config.seed, day_index, 商品名) から決定論的に再現できる。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .weather import weather_for

if TYPE_CHECKING:
    from .world import WorldState, DaySalesResult

# 曜日係数（月=0 .. 日=6）: 週末は人出が多い想定
DOW_MULT = [0.9, 0.9, 0.95, 1.0, 1.15, 1.3, 1.2]

# 月係数（1月=index0 .. 12月）: 夏に向けて需要増
MONTH_MULT = [0.85, 0.85, 0.9, 0.95, 1.05, 1.15, 1.2, 1.2, 1.1, 1.0, 0.9, 0.95]

# 品揃えの最適点（distinct 商品数）と下限係数
OPTIMAL_VARIETY = 4
CHOICE_FLOOR = 0.5


@dataclass(frozen=True)
class DemandParams:
    price_elasticity: float  # 負値
    reference_price: float
    base_sales: float

    def to_dict(self) -> dict:
        return {
            "price_elasticity": self.price_elasticity,
            "reference_price": self.reference_price,
            "base_sales": self.base_sales,
        }


def demand_params_for(world: "WorldState", product_name: str) -> DemandParams:
    """商品の需要パラメータを取得（初出時に決定論生成してキャッシュ）。"""
    cached = world.demand_params.get(product_name)
    if cached is not None:
        return DemandParams(**cached)

    rng = random.Random(f"{world.config.seed}:{product_name}")
    params = DemandParams(
        price_elasticity=round(rng.uniform(-2.5, -1.2), 3),
        reference_price=round(rng.uniform(1.5, 4.0), 2),
        base_sales=round(rng.uniform(3.0, 12.0), 2),
    )
    world.demand_params[product_name] = params.to_dict()
    return params


def choice_multiplier(distinct_products: int) -> float:
    """品揃えの多様性係数。最適点近傍で 1.0、過少・過多で減衰（下限 CHOICE_FLOOR）。"""
    if distinct_products <= 0:
        return CHOICE_FLOOR
    deviation = abs(distinct_products - OPTIMAL_VARIETY)
    # 過多は過少よりやや重く罰する
    penalty = 0.07 * deviation if distinct_products <= OPTIMAL_VARIETY else 0.10 * deviation
    return round(max(CHOICE_FLOOR, 1.0 - penalty), 4)


def simulate_day(world: "WorldState") -> "DaySalesResult":
    """当日（clock.day_index）の売上を確定する。在庫減・機内現金・クレジット予約を行う。"""
    from .world import DaySalesResult  # 循環 import 回避

    day = world.clock.day_index
    rng = random.Random((world.config.seed * 7_919) ^ (day * 32_452_843))

    weather = weather_for(world.config.seed, world.clock.date)
    dow = DOW_MULT[world.clock.weekday]
    month = MONTH_MULT[world.clock.month - 1]
    choice = choice_multiplier(world.machine.distinct_products())

    result = DaySalesResult()
    cash_ratio = world.config.cash_payment_ratio
    settle_day = day + world.config.credit_settlement_days

    for slot in world.machine.available_for_sale():
        p = demand_params_for(world, slot.product_name)
        pct_diff = (slot.price - p.reference_price) / p.reference_price
        price_impact = max(0.0, 1.0 + p.price_elasticity * pct_diff)
        expected = p.base_sales * price_impact * dow * month * weather.multiplier * choice
        noise = rng.gauss(0.0, max(0.5, expected * 0.15))
        sold = int(round(expected + noise))
        sold = max(0, min(sold, slot.quantity))
        if sold == 0:
            continue

        revenue = round(sold * slot.price, 2)
        cash_part = round(revenue * cash_ratio, 2)
        credit_part = round(revenue - cash_part, 2)

        world.machine.record_sale(slot, sold, cash_amount=cash_part)
        world.ledger.add_credit_sale(credit_part, settle_day=settle_day)

        result.units_sold += sold
        result.revenue_cash += cash_part
        result.revenue_credit += credit_part
        result.per_item[slot.product_name] = result.per_item.get(slot.product_name, 0) + sold

    result.revenue_cash = round(result.revenue_cash, 2)
    result.revenue_credit = round(result.revenue_credit, 2)
    world.total_units_sold += result.units_sold
    world.total_revenue = round(world.total_revenue + result.revenue_total, 2)
    return result
