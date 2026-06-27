"""複数ランの残高推移を可視化するスクリプト。

Usage:
    python scripts/visualize_runs.py [results_dir] [-o output.png]

結果:
    - X軸: day (シミュレーション経過日数)
    - Y軸: 残高 (balance)
    - 大きな変化・トレンド転換点に主要イベントをアノテーション
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_run(path: Path) -> dict:
    """JSONファイルからランデータを読み込む。"""
    with open(path) as f:
        return json.load(f)


def extract_daily_balance(data: dict) -> dict[int, float]:
    """トランザクションから日次残高（日末残高）を抽出する。"""
    txns = data["ledger"]["transactions"]
    daily: dict[int, float] = {}
    initial_balance = data["config"]["initial_balance"]
    # day 0: 初期残高
    daily[0] = initial_balance
    for t in txns:
        day = t["day"]
        daily[day] = t["balance_after"]
    return daily


def extract_events(data: dict) -> list[dict]:
    """主要イベント（注文・配送・大きな収入/支出）を抽出する。"""
    events = []
    txns = data["ledger"]["transactions"]

    # 1日の収支合計を集計してトレンド変化を検出
    daily_net: dict[int, float] = {}
    for t in txns:
        day = t["day"]
        daily_net[day] = daily_net.get(day, 0) + t["amount"]

    # 注文イベント
    for order in data.get("orders", []):
        events.append(
            {
                "day": order["created_day"],
                "label": f"Order#{order['id']} ${order['total']:.0f}",
                "kind": "order",
            }
        )
        if order["status"] in ("delivered", "paid"):
            events.append(
                {
                    "day": order["arrival_day"],
                    "label": f"Delivery#{order['id']}",
                    "kind": "delivery",
                }
            )

    # 大きな支出（購入）
    for t in txns:
        if t["kind"] == "purchase" and abs(t["amount"]) >= 50:
            events.append(
                {
                    "day": t["day"],
                    "label": f"Purchase ${abs(t['amount']):.0f}",
                    "kind": "purchase",
                }
            )

    # トークン課金
    for t in txns:
        if t["kind"] == "token_billing":
            events.append(
                {
                    "day": t["day"],
                    "label": f"AI Fee ${abs(t['amount']):.2f}",
                    "kind": "token",
                }
            )

    # 大きな売上入金（sale_credit + sale_cash が合計で大きい日）
    daily_sales: dict[int, float] = {}
    for t in txns:
        if t["kind"] in ("sale_credit", "sale_cash_collected"):
            daily_sales[t["day"]] = daily_sales.get(t["day"], 0) + t["amount"]

    if daily_sales:
        avg_sale = sum(daily_sales.values()) / len(daily_sales)
        threshold = avg_sale * 1.5
        for day, total in daily_sales.items():
            if total >= threshold and total >= 50:
                events.append(
                    {
                        "day": day,
                        "label": f"Sales ${total:.0f}",
                        "kind": "sale",
                    }
                )

    # 重複排除（同じ日・同じラベル）
    seen = set()
    unique = []
    for e in events:
        key = (e["day"], e["kind"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return sorted(unique, key=lambda e: e["day"])


def detect_trend_changes(daily_balance: dict[int, float], threshold: float = 30.0) -> list[int]:
    """残高の急激な変化点を検出する。"""
    days = sorted(daily_balance)
    changes = []
    for i in range(1, len(days)):
        prev_day = days[i - 1]
        curr_day = days[i]
        delta = daily_balance[curr_day] - daily_balance[prev_day]
        if abs(delta) >= threshold:
            changes.append(curr_day)
    return changes


def visualize(results_dir: Path, output: Path | None = None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    plt.rcParams["font.family"] = ["DejaVu Sans", "sans-serif"]

    json_files = sorted(results_dir.glob("*.json"))
    if not json_files:
        print(f"No JSON files found in {results_dir}")
        return

    # カラーパレット（ランごとに異なる色）
    colors = plt.get_cmap("tab10").colors

    fig, ax = plt.subplots(figsize=(14, 7))

    all_days: set[int] = set()
    run_data: list[tuple[str, dict[int, float], list[dict]]] = []

    for i, path in enumerate(json_files):
        data = load_run(path)
        daily = extract_daily_balance(data)
        events = extract_events(data)
        run_data.append((path.stem, daily, events))
        all_days.update(daily.keys())

    max_day = max(all_days) if all_days else 0

    # アノテーションのY位置をずらすためのオフセット管理
    annotation_y_offset: dict[int, int] = {}

    for i, (run_name, daily, events) in enumerate(run_data):
        color = colors[i % len(colors)]
        days = sorted(daily.keys())
        balances = [daily[d] for d in days]

        # 全日に対して線形補間（欠損日を埋める）
        if len(days) > 1:
            all_d = list(range(days[0], days[-1] + 1))
            all_b = np.interp(all_d, days, balances)
            ax.plot(all_d, all_b, color=color, linewidth=2.0, label=run_name, zorder=3)
            ax.scatter(days, balances, color=color, s=30, zorder=4)
        else:
            ax.scatter(days, balances, color=color, s=50, label=run_name, zorder=4)

        # イベントアノテーション
        event_color_map = {
            "order": "#e67e22",
            "delivery": "#27ae60",
            "purchase": "#e74c3c",
            "token": "#9b59b6",
            "sale": "#2980b9",
        }
        for ev in events:
            day = ev["day"]
            if day not in daily:
                # 最も近い日の残高を使う
                closest = min(daily.keys(), key=lambda d: abs(d - day))
                bal = daily[closest]
            else:
                bal = daily[day]

            # Y方向のオフセット（重なり防止）
            offset_count = annotation_y_offset.get(day, 0)
            annotation_y_offset[day] = offset_count + 1
            y_offset = 20 + offset_count * 18

            ekind = ev.get("kind", "order")
            ecolor = event_color_map.get(ekind, "#555555")
            ax.annotate(
                ev["label"],
                xy=(day, bal),
                xytext=(0, y_offset),
                textcoords="offset points",
                fontsize=7.5,
                color=ecolor,
                arrowprops=dict(arrowstyle="-", color=ecolor, lw=0.8, alpha=0.7),
                ha="center",
                va="bottom",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor=ecolor, alpha=0.85, linewidth=0.7),
                zorder=5,
            )

    # 初期残高の参照線
    initial_balance = run_data[0][1].get(0, 500) if run_data else 500
    ax.axhline(y=initial_balance, color="gray", linestyle="--", linewidth=1.0, alpha=0.6, label=f"Initial Balance ${initial_balance:.0f}")

    ax.set_xlabel("Day", fontsize=12)
    ax.set_ylabel("Balance ($)", fontsize=12)
    ax.set_title("Balance Over Time per Run", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.set_xlim(left=0)

    # イベント凡例パッチ
    legend_patches = [
        mpatches.Patch(color="#e67e22", label="Order"),
        mpatches.Patch(color="#27ae60", label="Delivery"),
        mpatches.Patch(color="#e74c3c", label="Large Purchase"),
        mpatches.Patch(color="#9b59b6", label="AI Fee"),
        mpatches.Patch(color="#2980b9", label="Large Sale"),
    ]
    ax.legend(
        handles=ax.get_legend_handles_labels()[0] + legend_patches,
        labels=ax.get_legend_handles_labels()[1] + [p.get_label() for p in legend_patches],
        loc="upper left",
        fontsize=8.5,
        ncol=2,
    )

    plt.tight_layout()

    if output is None:
        output = results_dir / "runs_balance.png"
    plt.savefig(output, dpi=150, bbox_inches="tight")
    print(f"Saved: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize vending bench run results")
    parser.add_argument("results_dir", nargs="?", default="results", help="Directory containing JSON run files")
    parser.add_argument("-o", "--output", default=None, help="Output PNG file path")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    output = Path(args.output) if args.output else None
    visualize(results_dir, output)


if __name__ == "__main__":
    main()
