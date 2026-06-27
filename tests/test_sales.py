"""Phase 2: 売上・天候シミュレーションのテスト。"""

from __future__ import annotations

from datetime import date

from vending_bench.config import EnvConfig
from vending_bench.env.world import WorldState
from vending_bench.env import sales as sales_mod
from vending_bench.env.weather import weather_for


def stocked_world(price: float = 2.5, qty: int = 15, seed: int = 0) -> WorldState:
    w = WorldState.new(EnvConfig(seed=seed))
    w.machine.stock("A1", product_name="Coke", size="small", quantity=qty, unit_cost=1.0)
    w.machine.set_price("A1", price)
    return w


# --------------------------------------------------------------------------- #
# 決定論・再現性
# --------------------------------------------------------------------------- #
def test_demand_params_cached_and_deterministic():
    w = stocked_world()
    p1 = sales_mod.demand_params_for(w, "Coke")
    p2 = sales_mod.demand_params_for(w, "Coke")
    assert p1 == p2
    assert "Coke" in w.demand_params
    assert p1.price_elasticity < 0


def test_same_seed_same_sales():
    a = stocked_world(seed=42)
    b = stocked_world(seed=42)
    ra = a.advance_to_next_day(sales_fn=sales_mod.simulate_day)
    rb = b.advance_to_next_day(sales_fn=sales_mod.simulate_day)
    assert ra.sales.units_sold == rb.sales.units_sold
    assert ra.sales.revenue_total == rb.sales.revenue_total


def test_weather_deterministic():
    w1 = weather_for(7, date(2026, 7, 4))
    w2 = weather_for(7, date(2026, 7, 4))
    assert w1 == w2
    assert 0.6 <= w1.multiplier <= 1.3


# --------------------------------------------------------------------------- #
# 価格弾力性
# --------------------------------------------------------------------------- #
def test_higher_price_reduces_sales():
    """高価格ほど販売数が減る（複数日平均で比較）。"""
    def total_units(price: float) -> int:
        total = 0
        w = stocked_world(price=price, qty=999, seed=5)
        # 在庫を十分に保ちつつ複数日回す
        for _ in range(20):
            w.machine.get_slot("A1").quantity = 999
            rep = w.advance_to_next_day(sales_fn=sales_mod.simulate_day)
            total += rep.sales.units_sold
        return total

    cheap = total_units(1.5)
    pricey = total_units(5.0)
    assert cheap > pricey


def test_sales_capped_by_inventory():
    w = stocked_world(price=1.0, qty=2, seed=1)  # 激安・低在庫
    rep = w.advance_to_next_day(sales_fn=sales_mod.simulate_day)
    assert rep.sales.units_sold <= 2
    assert w.machine.get_slot("A1").quantity >= 0


def test_no_sales_without_price():
    w = WorldState.new(EnvConfig(seed=3))
    w.machine.stock("A1", product_name="Coke", size="small", quantity=10, unit_cost=1.0)
    # 価格未設定（0）なら販売対象外
    rep = w.advance_to_next_day(sales_fn=sales_mod.simulate_day)
    assert rep.sales.units_sold == 0


# --------------------------------------------------------------------------- #
# 売上の現金/クレジット配分と入金
# --------------------------------------------------------------------------- #
def test_revenue_split_cash_and_credit():
    w = stocked_world(price=2.0, qty=999, seed=9)
    rep = w.advance_to_next_day(sales_fn=sales_mod.simulate_day)
    if rep.sales.units_sold > 0:
        # 現金は機内に貯まる
        assert w.machine.cash > 0
        # クレジットは翌日入金される（settlement=1日）
        assert rep.credits_settled >= 0


# --------------------------------------------------------------------------- #
# choice_mult
# --------------------------------------------------------------------------- #
def test_choice_multiplier_shape():
    from vending_bench.env.sales import choice_multiplier, OPTIMAL_VARIETY, CHOICE_FLOOR
    assert choice_multiplier(OPTIMAL_VARIETY) == 1.0
    assert choice_multiplier(0) == CHOICE_FLOOR
    # 過多は減衰し下限を割らない
    assert CHOICE_FLOOR <= choice_multiplier(20) <= 1.0
    assert choice_multiplier(12) < choice_multiplier(OPTIMAL_VARIETY)
