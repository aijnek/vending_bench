"""セッション運転モードの MCP サーバの単体テスト（claude は起動しない）。

`VBMCPServer.handle_request` に JSON-RPC メッセージを直接渡して、プロトコルの応答・
ツールスキーマ・ツール実行・永続化・秘匿性（環境内部が露出しないこと）を検証する。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vending_bench.env.world import WorldState
from vending_bench.mcp.server import (
    VBMCPServer,
    tool_descriptors,
    tool_input_schema,
)
from vending_bench.tools.schema import TOOLS, TOOLS_BY_NAME


@pytest.fixture()
def server(tmp_path: Path) -> VBMCPServer:
    return VBMCPServer(tmp_path / "state.json", seed=1)


def _call(server: VBMCPServer, method: str, params: dict | None = None, msg_id: int = 1):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle_request(msg)


# --------------------------------------------------------------------------- #
# プロトコル
# --------------------------------------------------------------------------- #
def test_initialize_echoes_protocol_version(server: VBMCPServer):
    resp = _call(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert resp["result"]["serverInfo"]["name"] == "vb"
    assert "tools" in resp["result"]["capabilities"]


def test_notification_returns_none(server: VBMCPServer):
    # id を持たない通知には応答しない。
    assert server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_is_rpc_error(server: VBMCPServer):
    resp = _call(server, "no_such_method")
    assert resp["error"]["code"] == -32601


def test_ping(server: VBMCPServer):
    assert _call(server, "ping")["result"] == {}


# --------------------------------------------------------------------------- #
# tools/list とスキーマ生成
# --------------------------------------------------------------------------- #
def test_tools_list_covers_all_tools(server: VBMCPServer):
    resp = _call(server, "tools/list")
    tools = resp["result"]["tools"]
    assert {t["name"] for t in tools} == set(TOOLS_BY_NAME)
    for t in tools:
        assert t["description"]
        assert t["inputSchema"]["type"] == "object"


def test_input_schema_types_and_required():
    spec = TOOLS_BY_NAME["send_payment"]
    schema = tool_input_schema(spec)
    assert schema["properties"]["amount"]["type"] == "number"
    assert schema["properties"]["to"]["type"] == "string"
    assert set(schema["required"]) == {"to", "amount"}
    # 省略可引数は required に入らない。
    n_schema = tool_input_schema(TOOLS_BY_NAME["get_balance_and_transactions"])
    assert n_schema["required"] == []
    assert n_schema["properties"]["n"]["type"] == "integer"


def test_descriptors_match_schema_module():
    assert len(tool_descriptors()) == len(TOOLS)


# --------------------------------------------------------------------------- #
# tools/call
# --------------------------------------------------------------------------- #
def test_tools_call_runs_tool(server: VBMCPServer):
    resp = _call(server, "tools/call", {"name": "get_balance_and_transactions", "arguments": {}})
    result = resp["result"]
    assert result["isError"] is False
    assert "残高" in result["content"][0]["text"]


def test_tools_call_unknown_tool_is_tool_error(server: VBMCPServer):
    resp = _call(server, "tools/call", {"name": "drop_table", "arguments": {}})
    # プロトコルエラーではなく isError コンテンツで返す（セッションは継続可能）。
    assert "error" not in resp
    assert resp["result"]["isError"] is True
    assert "未知のツール" in resp["result"]["content"][0]["text"]


def test_tools_call_missing_required_arg_is_tool_error(server: VBMCPServer):
    resp = _call(server, "tools/call", {"name": "set_price", "arguments": {"slot": "A1"}})
    assert resp["result"]["isError"] is True
    assert "Tool error" in resp["result"]["content"][0]["text"]


def test_tools_call_coerces_string_numbers(server: VBMCPServer):
    # MCP 引数が文字列で来ても execute 側で型変換される。
    resp = _call(server, "tools/call",
                 {"name": "get_balance_and_transactions", "arguments": {"n": "3"}})
    assert resp["result"]["isError"] is False


def test_wait_for_next_day_advances_and_persists(server: VBMCPServer, tmp_path: Path):
    assert server.world.clock.day_index == 0
    resp = _call(server, "tools/call", {"name": "wait_for_next_day", "arguments": {}})
    assert resp["result"]["isError"] is False
    assert server.world.clock.day_index == 1
    # 状態がファイルに保存されている（オーケストレータが読み直せる）。
    reloaded = WorldState.load(tmp_path / "state.json")
    assert reloaded.clock.day_index == 1


def test_state_loaded_from_existing_file(tmp_path: Path):
    s1 = VBMCPServer(tmp_path / "s.json", seed=1)
    _call(s1, "tools/call", {"name": "wait_for_next_day", "arguments": {}})
    # 同じファイルを指す新サーバは続きの状態を読む。
    s2 = VBMCPServer(tmp_path / "s.json", seed=1)
    assert s2.world.clock.day_index == 1


# --------------------------------------------------------------------------- #
# 秘匿性: 公開面に環境内部が漏れないこと
# --------------------------------------------------------------------------- #
def test_no_internal_fields_exposed_in_tool_surface(server: VBMCPServer):
    surface = json.dumps(_call(server, "tools/list")["result"], ensure_ascii=False)
    # サプライヤーの誠実さ・天候・需要などの内部語彙が tools/list に現れない。
    for secret in ("scam", "honest", "weather", "demand", "supplier_runtime", "seed"):
        assert secret not in surface.lower()


# --------------------------------------------------------------------------- #
# stdio エンドツーエンド（サブプロセスで JSON-RPC を流す）
# --------------------------------------------------------------------------- #
def test_stdio_end_to_end(tmp_path: Path):
    state = tmp_path / "e2e.json"
    env = {
        "VB_STATE_PATH": str(state),
        "VB_SEED": "1",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "get_inventory", "arguments": {}}}),
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "vending_bench.mcp.server"],
        input="\n".join(lines) + "\n",
        capture_output=True, text=True, env=env, timeout=30,
    )
    out_lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    by_id = {m.get("id"): m for m in out_lines}
    assert by_id[1]["result"]["serverInfo"]["name"] == "vb"
    assert {t["name"] for t in by_id[2]["result"]["tools"]} == set(TOOLS_BY_NAME)
    assert by_id[3]["result"]["isError"] is False
    assert state.exists()
