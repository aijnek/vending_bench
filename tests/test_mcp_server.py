"""MCP サーバ層（skill モード）のテスト。

実行時挙動は tools.api.execute 側のテストでカバー済みなので、ここでは MCP 固有の
部分（スキーマ生成・補助ツールの出力・サーバ構築・委譲の同値性）を確認する。
"""

from __future__ import annotations

import anyio

from vending_bench import mcp_server as mcp
from vending_bench.config import EnvConfig
from vending_bench.env.world import WorldState
from vending_bench.tools.api import execute
from vending_bench.tools.schema import TOOLS, TOOLS_BY_NAME


def _fresh(seed: int = 1) -> WorldState:
    return WorldState.new(EnvConfig(seed=seed))


def test_tool_schema_maps_types_and_required():
    spec = TOOLS_BY_NAME["send_payment"]  # to:string(req), amount:float(req)
    tool = mcp._tool_to_mcp(spec)
    props = tool.inputSchema["properties"]
    assert props["to"]["type"] == "string"
    assert props["amount"]["type"] == "number"  # float -> number
    assert set(tool.inputSchema["required"]) == {"to", "amount"}

    # 任意引数は required に入らない（web_search.query は optional）
    ws = mcp._tool_to_mcp(TOOLS_BY_NAME["web_search"])
    assert ws.inputSchema["required"] == []

    # int -> integer
    re = mcp._tool_to_mcp(TOOLS_BY_NAME["set_reminder"])
    assert re.inputSchema["properties"]["day"]["type"] == "integer"


def test_build_server_lists_all_tools_plus_helpers():
    server = mcp.build_server()
    handler = server.request_handlers
    # list_tools ハンドラ経由で件数を確認
    import mcp.types as types

    result = anyio.run(lambda: handler[types.ListToolsRequest](
        types.ListToolsRequest(method="tools/list")))
    names = {t.name for t in result.root.tools}
    assert names == set(TOOLS_BY_NAME) | {"get_briefing", "get_status"}


def test_get_briefing_is_visible_rules_only():
    mcp.WORLD = _fresh()
    mcp.TARGET_DAYS = 5
    text = mcp.business_briefing(mcp.WORLD.config, mention_token_cost=False)
    assert "vending machine business" in text
    # skill モードはトークン課金を出さない
    assert "output tokens" not in text
    # 地の真実（reliability/markup/weather 等）は briefing に現れない
    for leak in ("reliability", "markup", "elasticity", "weather"):
        assert leak not in text.lower()


def test_status_reports_progress_and_finish():
    w = _fresh()
    mcp.WORLD = w
    mcp.TARGET_DAYS = 2
    assert "run_finished: False" in mcp._status_text(w)
    execute(w, "wait_for_next_day")
    execute(w, "wait_for_next_day")
    assert w.clock.day_index == 2
    assert "run_finished: True" in mcp._status_text(w)


def test_call_tool_delegates_to_execute():
    """call_tool ハンドラの結果が execute と一致することを確認。"""
    import mcp.types as types

    server = mcp.build_server()
    handler = server.request_handlers[types.CallToolRequest]

    mcp.WORLD = _fresh(seed=3)
    mcp.TARGET_DAYS = 5
    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="web_search", arguments={"query": "soda"}),
    )
    result = anyio.run(lambda: handler(req))
    text = result.root.content[0].text

    # 同一シードの別世界で execute を直接呼んだ結果と一致
    expected = execute(_fresh(seed=3), "web_search", {"query": "soda"})
    assert text == expected
