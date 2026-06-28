"""単一セッション運転用の MCP stdio サーバ（skill モードのツール層）。

コーディングエージェント（Claude Code 等）が 1 セッション内で自律的にツールを
呼び続けて自販機ビジネスを運転するための入口。`WorldState` をこのサーバ
プロセスのメモリ内にのみ保持するため、サプライヤーの性質・天気・需要などの
「地の真実」はディスクにもツール出力にも現れず、エージェントからは
公開された 14 ツール ＋ get_briefing / get_status だけが見える。

実行時の挙動（引数検証・型変換・時間進行・日送り）は既存の
`tools.api.execute` / `WorldState` をそのまま再利用する（MCP 層は透過的な委譲のみ）。

構成は環境変数で行う（エージェントには渡さない）:
    VB_SEED         乱数シード（既定 0）
    VB_TARGET_DAYS  運転する日数の上限（既定 = config.duration_days）
    VB_SUPPLIERS    サプライヤー返信エンジン llm | rule（既定 llm）

トークン課金（$100/1M output, 週次）は skill モードでは行わない。
"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .agent.prompts import business_briefing
from .config import EnvConfig
from .env import events as events_mod
from .env.suppliers.rule_based import RuleBasedNegotiationEngine
from .env.world import WorldState
from .tools.api import ToolError, execute
from .tools.schema import TOOLS

# JSON Schema へのプリミティブ型対応（schema.py の "string"|"int"|"float"）。
_JSON_TYPE = {"string": "string", "int": "integer", "float": "number"}

# プロセス内に 1 つだけ保持する世界とその運転上限。main() で初期化。
WORLD: WorldState | None = None
TARGET_DAYS: int = 0
SAVE_PATH: Path | None = None


def _tool_to_mcp(spec) -> types.Tool:
    """ToolSpec を MCP の Tool 定義（入力スキーマ付き）へ変換する。"""
    properties: dict[str, dict] = {}
    required: list[str] = []
    for p in spec.params:
        properties[p.name] = {"type": _JSON_TYPE[p.type], "description": p.description}
        if p.required:
            required.append(p.name)
    return types.Tool(
        name=spec.name,
        description=f"{spec.description}（所要 {spec.duration_min} 分）",
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    )


_BRIEFING_TOOL = types.Tool(
    name="get_briefing",
    description="自分の役割・ゴール・ルール・初期状況を取得する。最初に必ず呼ぶこと。",
    inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
)

_STATUS_TOOL = types.Tool(
    name="get_status",
    description="現在の経過日数・時刻・状態・運転終了かどうかを取得する。"
                "終了判定と「就寝すべきか」の判断に使う（地の真実は返さない）。",
    inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
)


def _initial_observation(world: WorldState) -> str:
    return (
        f"It is the morning of Day {world.clock.day_index}. Your vending machine is empty and "
        f"unstocked. Balance: ${world.ledger.balance:.2f}. Inbox: {len(world.mailbox.unread())} "
        f"unread. Begin building your business: research suppliers (web_search), source products "
        f"at good prices, stock the machine, set prices, then sell. You will run for up to "
        f"{TARGET_DAYS} day(s). After finishing each day's work, call wait_for_next_day to sleep "
        f"and let sales, deliveries and new emails settle — days do NOT advance otherwise."
    )


def _status_text(world: WorldState) -> str:
    reached = world.is_terminal or world.clock.day_index >= TARGET_DAYS
    return (
        f"day_index: {world.clock.day_index} / target_days: {TARGET_DAYS}\n"
        f"current_time: {world.clock.current:%Y-%m-%d %H:%M}\n"
        f"net_worth: ${world.net_worth():.2f} / balance: ${world.ledger.balance:.2f}\n"
        f"status: {world.status}\n"
        f"run_finished: {reached}"
        + ("\n（運転終了。これ以上の操作は不要です。）" if reached else "")
    )


def build_server() -> Server:
    server: Server = Server("vending")
    mcp_tools = [_tool_to_mcp(t) for t in TOOLS] + [_BRIEFING_TOOL, _STATUS_TOOL]

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return mcp_tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        assert WORLD is not None
        args = arguments or {}
        print(
            f"[vb | day {WORLD.clock.day_index} | ${WORLD.ledger.balance:.2f}] "
            f"→ {name} {args}",
            file=sys.stderr, flush=True,
        )
        if name == "get_briefing":
            text = business_briefing(WORLD.config, mention_token_cost=False) + "\n\n" \
                + _initial_observation(WORLD)
        elif name == "get_status":
            text = _status_text(WORLD)
        else:
            try:
                # execute は同期。LLM サプライヤーエンジン（wait_for_next_day）が
                # claude サブプロセスを呼ぶことがあるため別スレッドで実行しイベント
                # ループを塞がない。
                text = await anyio.to_thread.run_sync(execute, WORLD, name, args)
            except ToolError as exc:
                text = f"Tool error: {exc}"
            if name == "wait_for_next_day" and SAVE_PATH is not None:
                WORLD.save(SAVE_PATH)
        print(f"[vb] ← {text[:120]!r}", file=sys.stderr, flush=True)
        return [types.TextContent(type="text", text=text)]

    return server


def _make_world() -> WorldState:
    seed = int(os.environ.get("VB_SEED", "0"))
    config = EnvConfig(seed=seed)
    world = WorldState.new(config)

    mode = os.environ.get("VB_SUPPLIERS", "llm").strip().lower()
    if mode == "rule":
        events_mod.set_engine(RuleBasedNegotiationEngine())
    else:
        # 既定は LLM エンジン（サーバ側で claude haiku を呼ぶ＝隠蔽）。
        from .agent.llm import ClaudeCLI
        from .env.suppliers.llm_based import LLMNegotiationEngine
        events_mod.set_engine(LLMNegotiationEngine(cli=ClaudeCLI(model="haiku", timeout_s=60)))
    return world


async def _run() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    global WORLD, TARGET_DAYS, SAVE_PATH
    WORLD = _make_world()
    TARGET_DAYS = int(os.environ.get("VB_TARGET_DAYS", str(WORLD.config.duration_days)))
    save_env = os.environ.get("VB_SAVE_PATH", "")
    if save_env:
        SAVE_PATH = Path(save_env)
        SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        atexit.register(lambda: WORLD.save(SAVE_PATH) if WORLD else None)
        print(f"[vb] 保存先: {SAVE_PATH}", file=sys.stderr, flush=True)
    anyio.run(_run)


if __name__ == "__main__":
    main()
