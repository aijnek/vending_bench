"""自前エージェントループ（MCP不要）。

各ターン: トリミング済み履歴＋システムプロンプトを `claude -p` に渡して次アクション(JSON)を取得 →
パースして tools/api を実行 → 結果を履歴へ。出力トークンは sim 内の残高から週次課金される。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import EnvConfig
from ..env.world import WorldState
from ..scoring import RunMetrics, score_breakdown
from ..tools.api import ToolError, execute
from .llm import ClaudeCLI, LLMError
from .memory import ConversationMemory, parse_tool_call
from .prompts import CONTINUE_REMINDER, NEXT_ACTION_INSTRUCTION, system_prompt

MAX_CONSECUTIVE_ERRORS = 8


def _initial_observation(world: WorldState) -> str:
    return (
        f"It is the morning of Day 0. Your vending machine is empty and unstocked. "
        f"Balance: ${world.ledger.balance:.2f}. Inbox: {len(world.mailbox.unread())} unread. "
        f"Begin building your business: research suppliers, source products at good prices, "
        f"stock the machine, set prices, and sell. Use web_search first if you need supplier contacts."
    )


def run_agent(world: WorldState, llm: ClaudeCLI, *, days: int, max_steps: int,
              memory: ConversationMemory, state_path: Path | None = None,
              verbose: bool = True, metrics: RunMetrics | None = None) -> dict:
    sys_prompt = system_prompt(world.config)
    memory.add_observation(_initial_observation(world))
    metrics = metrics if metrics is not None else RunMetrics()

    target_day = world.clock.day_index + days
    consecutive_errors = 0
    step = 0

    while step < max_steps and not world.is_terminal and world.clock.day_index < target_day:
        step += 1
        user_prompt = memory.render() + "\n\n" + NEXT_ACTION_INSTRUCTION

        try:
            resp = llm.complete(sys_prompt, user_prompt)
        except LLMError as exc:
            print(f"[step {step}] LLM エラー: {exc}")
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print("LLM エラーが連続したため中断します。")
                break
            continue

        world.ledger.record_output_tokens(resp.output_tokens)
        memory.add_action(resp.text)

        try:
            call = parse_tool_call(resp.text)
        except ValueError as exc:
            consecutive_errors += 1
            feedback = (f"Your response could not be parsed ({exc}). Respond with exactly one JSON "
                        f'object: {{"thought": "...", "tool": "...", "args": {{...}}}}.')
            memory.add_observation(feedback)
            if verbose:
                print(f"[step {step}] パース失敗: {resp.text[:120]!r}")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print("パース失敗が連続したため中断します。")
                break
            continue

        tool = call["tool"]
        args = call["args"]
        day_before = world.clock.day_index
        try:
            result = execute(world, tool, args)
            consecutive_errors = 0
            metrics.record_tool(tool)
            if world.clock.day_index > day_before:
                metrics.record_day(world.clock.day_index, world.net_worth())
        except ToolError as exc:
            consecutive_errors += 1
            result = f"Tool error: {exc}"
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                memory.add_observation(result + "\n" + CONTINUE_REMINDER)
                print("ツールエラーが連続したため中断します。")
                break

        memory.add_observation(result)
        if verbose:
            thought = call.get("thought", "")
            print(f"[step {step} | day {world.clock.day_index} | ${world.ledger.balance:.2f}] "
                  f"{tool} {json.dumps(args, ensure_ascii=False)}"
                  + (f"  // {thought}" if thought else ""))

        if state_path is not None and step % 20 == 0:
            world.save(state_path)

    summary = {
        "steps": step,
        "score": score_breakdown(world),
        "tool_counts": metrics.tool_counts,
        "net_worth_by_day": metrics.net_worth_by_day,
    }
    if state_path is not None:
        world.save(state_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Vending-Bench 風シミュレーション エージェント自動運転")
    parser.add_argument("--days", type=int, default=5, help="運転する sim 日数（既定5）")
    parser.add_argument("--max-steps", type=int, default=None, help="安全上限のステップ数（既定 days*60）")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", type=str, default="sonnet", help="claude のモデル（sonnet/opus 等）")
    parser.add_argument("--state", type=Path, default=Path("results/run.json"), help="状態の保存先（途中保存・最終保存）")
    parser.add_argument("--context-tokens", type=int, default=8000, help="履歴コンテキストの概算トークン上限")
    parser.add_argument("--timeout", type=int, default=180, help="claude 1呼び出しのタイムアウト秒")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    args.state.parent.mkdir(parents=True, exist_ok=True)
    if args.state and args.state.exists():
        world = WorldState.load(args.state)
        print(f"ロードしました: {args.state}")
    else:
        world = WorldState.new(EnvConfig(seed=args.seed))

    max_steps = args.max_steps if args.max_steps is not None else args.days * 60
    llm = ClaudeCLI(model=args.model, timeout_s=args.timeout)
    memory = ConversationMemory(context_tokens=args.context_tokens)

    print(f"=== エージェント運転開始: {args.days}日 / 最大{max_steps}ステップ / model={args.model} ===")
    summary = run_agent(world, llm, days=args.days, max_steps=max_steps,
                        memory=memory, state_path=args.state, verbose=not args.quiet)
    print("\n=== 結果 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
