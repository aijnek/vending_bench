"""日次天候の決定論的生成。

(seed, 日付) から再現可能に天候を生成する。状態は持たず純粋関数として扱える。
サンフランシスコ（北半球・温暖）を想定した季節分布。晴れ・暖かいと売上↑、雨・寒いと↓。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

Condition = str  # "sunny" | "cloudy" | "rainy"

# 月ごとの平均気温（摂氏, SF 近似）と降雨確率
_MONTHLY_TEMP_C = [11, 12, 13, 14, 15, 17, 17, 18, 19, 17, 14, 11]
_MONTHLY_RAIN_P = [0.35, 0.32, 0.28, 0.15, 0.08, 0.03, 0.01, 0.01, 0.03, 0.10, 0.25, 0.34]


@dataclass(frozen=True)
class Weather:
    condition: Condition
    temperature_c: float
    multiplier: float
    """売上に掛ける天候係数（おおむね 0.75〜1.20）。"""


def _rng_for(seed: int, d: date) -> random.Random:
    return random.Random((seed * 1_000_003) ^ (d.toordinal() * 2_654_435_761))


def weather_for(seed: int, d: date) -> Weather:
    rng = _rng_for(seed, d)
    m = d.month - 1
    rain_p = _MONTHLY_RAIN_P[m]
    roll = rng.random()
    if roll < rain_p:
        condition: Condition = "rainy"
    elif roll < rain_p + 0.30:
        condition = "cloudy"
    else:
        condition = "sunny"

    temp = _MONTHLY_TEMP_C[m] + rng.uniform(-3.0, 3.0)

    # 係数: 晴れ+1.0基準、雨は減、暖かいほど飲料が売れる
    cond_factor = {"sunny": 1.10, "cloudy": 1.0, "rainy": 0.80}[condition]
    # 18℃を中立とした緩い気温効果（±0.1程度）
    temp_factor = 1.0 + max(-0.12, min(0.12, (temp - 18.0) * 0.012))
    multiplier = round(cond_factor * temp_factor, 4)

    return Weather(condition=condition, temperature_c=round(temp, 1), multiplier=multiplier)
