"""人間操作用の CLI REPL（Phase 5）。

環境を手動で動かして挙動を確認するための対話シェル。ツール層（tools/api）を
そのまま叩くだけなので、後段のエージェントと完全に同じ操作面を共有する。

使い方:
    uv run vb-play                  # 新規ワールド（seed=0）
    uv run vb-play --seed 7
    uv run vb-play --state run.json # 既存状態をロード（quit 時に自動保存）
"""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from ..config import EnvConfig
from ..env.world import WorldState
from ..tools.api import ToolError, execute
from ..tools.schema import TOOLS, TOOLS_BY_NAME

INTRO = """\
=== Vending-Bench 風シミュレーション（人間操作モード）===
コマンド: <ツール名> [引数...] / help / tools / status / save [path] / quit
ツール名だけ入力すると引数を対話的に尋ねます。例:  set_price A1 2.5  /  read_email 3
"""


def _print_tools() -> None:
    print("利用可能なツール:")
    for t in TOOLS:
        ps = " ".join(f"<{p.name}{'?' if not p.required else ''}>" for p in t.params)
        print(f"  {t.name} {ps}".rstrip() + f"  [{t.duration_min}min]")
        print(f"      {t.description}")


def _print_status(world: WorldState) -> None:
    c = world.clock
    print(f"--- Day {c.day_index}/{world.config.duration_days}  {c.current:%Y-%m-%d %H:%M} "
          f"({['月','火','水','木','金','土','日'][c.weekday]})  状態: {world.status} ---")
    print(f"残高: ${world.ledger.balance:.2f} | 機内現金: ${world.machine.cash:.2f} | "
          f"純資産: ${world.net_worth():.2f} | 未読メール: {len(world.mailbox.unread())}")
    pending_orders = [o for o in world.orders if o.status in ("awaiting_payment", "paid")]
    if pending_orders:
        print("進行中の注文: " + ", ".join(f"#{o.id}({o.status},${o.total:.2f})" for o in pending_orders))


def _collect_args(spec, positional: list[str]) -> dict:
    """位置引数をスキーマにマップ。不足分は対話プロンプトで補う。最後の string 引数は残りを連結。"""
    args: dict[str, str] = {}
    params = list(spec.params)
    for i, p in enumerate(params):
        is_last = i == len(params) - 1
        if positional:
            if is_last and p.type == "string":
                args[p.name] = " ".join(positional)
                positional = []
            else:
                args[p.name] = positional.pop(0)
        elif p.required:
            prompt = f"  {p.name} ({p.type}) — {p.description}: "
            val = input(prompt).strip()
            if val:
                args[p.name] = val
        # 省略可の引数は位置指定がなければプロンプトしない
    return args


def run_repl(world: WorldState, state_path: Path | None) -> None:
    print(INTRO)
    _print_status(world)
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        try:
            tokens = shlex.split(line)
        except ValueError:
            tokens = line.split()
        cmd, *rest = tokens

        if cmd in ("quit", "exit", "q"):
            break
        if cmd in ("help", "h", "?"):
            print(INTRO)
            continue
        if cmd == "tools":
            _print_tools()
            continue
        if cmd == "status":
            _print_status(world)
            continue
        if cmd == "save":
            path = Path(rest[0]) if rest else state_path
            if path is None:
                print("保存先パスを指定してください: save <path>")
            else:
                world.save(path)
                state_path = path
                print(f"保存しました: {path}")
            continue

        spec = TOOLS_BY_NAME.get(cmd)
        if spec is None:
            print(f"未知のコマンド/ツール: {cmd}（'tools' で一覧）")
            continue
        try:
            args = _collect_args(spec, rest)
            result = execute(world, cmd, args)
        except ToolError as exc:
            print(f"エラー: {exc}")
            continue
        print(result)
        if world.is_terminal:
            print(f"\n*** シミュレーション終了（{world.status}）。最終純資産: ${world.net_worth():.2f} ***")

    if state_path is not None:
        world.save(state_path)
        print(f"状態を保存しました: {state_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vending-Bench 風シミュレーション 人間操作 REPL")
    parser.add_argument("--state", type=Path, default=None, help="状態ファイル（存在すればロード、quit 時に保存）")
    parser.add_argument("--seed", type=int, default=0, help="新規ワールドの乱数シード")
    parser.add_argument("--new", action="store_true", help="--state があっても新規作成する")
    args = parser.parse_args()

    if args.state and args.state.exists() and not args.new:
        world = WorldState.load(args.state)
        print(f"ロードしました: {args.state}")
    else:
        world = WorldState.new(EnvConfig(seed=args.seed))

    run_repl(world, args.state)


if __name__ == "__main__":
    main()
