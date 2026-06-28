"""ワンショット ツール実行 CLI（`vb-tool`）。

Claude Code セッション自身がプレイヤーとして 14 ツールを1手ずつ叩くための橋渡し。
1 プロセス = 1 ツール実行で、状態は `--state` の JSON に load/save される。
出力は REPL/エージェントループと同じ `tools.api.execute` の結果文字列＋機械可読な `STATUS` フッタ。

使い方:
    uv run vb-tool --state results/play.json tools                  # ツール一覧
    uv run vb-tool --state results/play.json briefing               # ビジネス文脈ブリーフィング
    uv run vb-tool --state results/play.json get_balance_and_transactions
    uv run vb-tool --state results/play.json --reason "翌朝へ" wait_for_next_day
    uv run vb-tool --state results/play.json send_email '{"to":"a@b.c","subject":"s","body":"b"}'

状態ファイル（--state）は `vb-run` と同一の WorldState ダンプ形式なので、
`scripts/visualize_runs.py` がそのまま使える。

サプライヤー返信エンジンは既定で LLM（haiku）＝ `vb-run` と同じ。`--supplier-engine rule` で
決定的なルールベース（追加 API 呼び出しなし）に切り替えられる。

トークン課金: `--reason` のテキスト長から出力トークンを概算し（CHARS_PER_TOKEN=4）、
`ledger.record_output_tokens` に積む。週次課金は wait_for_next_day 経由で自動発火し、
`claude -p` 版（agent/loop.py）の挙動を再現する。`--tokens` で明示上書きも可能。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..agent.memory import CHARS_PER_TOKEN
from ..config import EnvConfig
from ..env import events as events_mod
from ..env.world import WorldState
from ..tools.api import ToolError, execute
from ..tools.schema import TOOLS


def _print_tools() -> None:
    print("利用可能なツール:")
    for t in TOOLS:
        ps = " ".join(f"<{p.name}{'?' if not p.required else ''}>" for p in t.params)
        print(f"  {t.name} {ps}".rstrip() + f"  [{t.duration_min}min]")
        print(f"      {t.description}")


def _status_footer(world: WorldState) -> str:
    c = world.clock
    return (
        f"STATUS day={c.day_index}/{world.config.duration_days} "
        f"balance={world.ledger.balance:.2f} machine_cash={world.machine.cash:.2f} "
        f"net_worth={world.net_worth():.2f} status={world.status} "
        f"unread={len(world.mailbox.unread())} "
        f"tokens_unbilled={world.ledger.output_tokens_unbilled}"
    )


def _set_supplier_engine(mode: str) -> None:
    if mode == "llm":
        # vb-run と同じく haiku でサプライヤー返信を生成
        from ..agent.llm import ClaudeCLI
        from ..env.suppliers.llm_based import LLMNegotiationEngine
        events_mod.set_engine(LLMNegotiationEngine(cli=ClaudeCLI(model="haiku", timeout_s=60)))
    else:
        # "rule": 決定的・追加 API 呼び出しなし
        from ..env.suppliers.rule_based import RuleBasedNegotiationEngine
        events_mod.set_engine(RuleBasedNegotiationEngine())


def main() -> None:
    parser = argparse.ArgumentParser(description="Vending-Bench ワンショット ツール実行 CLI")
    parser.add_argument("--state", type=Path, default=Path("results/play.json"),
                        help="状態ファイル（存在すればロード、実行後に保存。既定 results/play.json）")
    parser.add_argument("--seed", type=int, default=0, help="新規ワールド作成時の乱数シード")
    parser.add_argument("--new", action="store_true", help="--state があっても新規作成する")
    parser.add_argument("--reason", type=str, default="",
                        help="この手の思考テキスト。長さから出力トークンを概算し課金する")
    parser.add_argument("--tokens", type=int, default=None,
                        help="課金する出力トークン数を明示指定（--reason 推定を上書き）")
    parser.add_argument("--supplier-engine", choices=("rule", "llm"), default="llm",
                        help="サプライヤー返信エンジン（既定 llm = vb-run と同じ haiku 生成。rule で決定的・追加API呼び出しなし）")
    parser.add_argument("tool", help="実行するツール名（'tools' でツール一覧 / 'briefing' でビジネス文脈）")
    parser.add_argument("args", nargs="?", default=None,
                        help="ツール引数の JSON オブジェクト（例 '{\"to\":\"a@b.c\"}'）")
    args = parser.parse_args()

    if args.tool == "tools":
        _print_tools()
        return

    if args.tool == "briefing":
        from ..agent.prompts import business_briefing
        if args.state.exists() and not args.new:
            cfg = WorldState.load(args.state).config
        else:
            cfg = EnvConfig(seed=args.seed)
        print(business_briefing(cfg))
        return

    # 引数 JSON のパース
    if args.args:
        try:
            tool_args = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(f"args は JSON オブジェクトで指定してください: {exc}", file=sys.stderr)
            sys.exit(2)
        if not isinstance(tool_args, dict):
            print("args は JSON オブジェクト（辞書）である必要があります。", file=sys.stderr)
            sys.exit(2)
    else:
        tool_args = {}

    # 状態のロード／新規作成
    args.state.parent.mkdir(parents=True, exist_ok=True)
    if args.state.exists() and not args.new:
        world = WorldState.load(args.state)
    else:
        world = WorldState.new(EnvConfig(seed=args.seed))

    _set_supplier_engine(args.supplier_engine)

    # トークン課金（記録 → 実行 の順。agent/loop.py と同じ）
    est_tokens = args.tokens if args.tokens is not None else len(args.reason) // CHARS_PER_TOKEN
    if est_tokens > 0:
        world.ledger.record_output_tokens(est_tokens)

    # ツール実行
    try:
        result = execute(world, args.tool, tool_args)
    except ToolError as exc:
        world.save(args.state)  # トークン記録を失わないよう保存
        print(f"エラー: {exc}", file=sys.stderr)
        sys.exit(1)

    world.save(args.state)
    print(result)
    print(_status_footer(world))


if __name__ == "__main__":
    main()
