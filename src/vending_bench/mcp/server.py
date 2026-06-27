"""依存ゼロの stdio JSON-RPC (MCP) サーバ。

`tools/schema.py` の 15 ツールをそのまま MCP ツールとして公開し、`tools/api.execute`
で WorldState を操作する。状態は `VB_STATE_PATH` のファイルにロード/セーブされ、
ツール呼び出しのたびに永続化される。

設計上の要点:
- **秘匿性**: WorldState とサプライヤー/天候/需要などの実装はこのプロセス内だけに存在する。
  エージェント側に見えるのは MCP の `tools/list`（名前・説明・引数スキーマ）と各呼び出しの
  結果テキストのみ。環境の「答え」は一切露出しない。
- **トークン課金**: ここではモデルの出力トークン数を観測できないため、課金はオーケストレータ
  （`agent/session.py`）が各ラウンドの実トークン数を `record_output_tokens` で注入する
  （従来の `agent/loop.py` と同じ責務分担）。サーバ自身は課金しない。

stdio トランスポート: 改行区切りの JSON-RPC 2.0。1 行 = 1 メッセージ。stdout には JSON-RPC
応答のみを書き、ログはすべて stderr に出す（stdout を汚すとプロトコルが壊れるため）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from ..config import EnvConfig
from ..env.world import WorldState
from ..tools.api import ToolError, execute
from ..tools.schema import TOOLS, TOOLS_BY_NAME

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "vb"
SERVER_VERSION = "0.1.0"

# スキーマ型 -> JSON Schema 型
_JSON_TYPE = {"string": "string", "int": "integer", "float": "number"}


def _log(msg: str) -> None:
    """stdout を汚さないよう、ログは必ず stderr へ。"""
    print(f"[vb-mcp] {msg}", file=sys.stderr, flush=True)


def tool_input_schema(spec) -> dict:
    """ToolSpec から MCP の inputSchema(JSON Schema) を生成する。"""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in spec.params:
        prop: dict[str, Any] = {"type": _JSON_TYPE[p.type]}
        if p.description:
            prop["description"] = p.description
        properties[p.name] = prop
        if p.required:
            required.append(p.name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_descriptors() -> list[dict]:
    """tools/list 応答用のツール記述子一覧。"""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "inputSchema": tool_input_schema(spec),
        }
        for spec in TOOLS
    ]


class VBMCPServer:
    """WorldState を保持し JSON-RPC リクエストを処理する MCP サーバ。"""

    def __init__(self, state_path: Path, seed: int = 0):
        self.state_path = Path(state_path)
        if self.state_path.exists():
            self.world = WorldState.load(self.state_path)
            _log(f"state をロード: {self.state_path} (day {self.world.clock.day_index})")
        else:
            self.world = WorldState.new(EnvConfig(seed=seed))
            self._save()
            _log(f"新規 world を作成 (seed={seed}) -> {self.state_path}")

    # ------------------------------------------------------------------ #
    # 永続化
    # ------------------------------------------------------------------ #
    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.world.save(self.state_path)

    # ------------------------------------------------------------------ #
    # JSON-RPC ディスパッチ
    # ------------------------------------------------------------------ #
    def handle_request(self, msg: dict) -> dict | None:
        """1 件の JSON-RPC メッセージを処理する。通知(idなし)には None を返す。"""
        method = msg.get("method")
        msg_id = msg.get("id")
        is_notification = "id" not in msg

        try:
            if method == "initialize":
                result = self._initialize(msg.get("params") or {})
            elif method in ("notifications/initialized", "notifications/cancelled"):
                return None  # 通知: 応答なし
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": tool_descriptors()}
            elif method == "tools/call":
                result = self._tools_call(msg.get("params") or {})
            elif method == "shutdown":
                result = {}
            else:
                if is_notification:
                    return None
                return _error(msg_id, -32601, f"Method not found: {method}")
        except _RpcError as exc:
            return _error(msg_id, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 — プロトコルを落とさず内部エラーを返す
            _log(f"内部エラー: {exc!r}")
            if is_notification:
                return None
            return _error(msg_id, -32603, f"Internal error: {exc}")

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _initialize(self, params: dict) -> dict:
        # クライアントが要求したプロトコルバージョンに合わせる（不明なら既定値）。
        version = params.get("protocolVersion") or PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def _tools_call(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _tool_error("arguments はオブジェクトである必要があります。")
        if name not in TOOLS_BY_NAME:
            return _tool_error(
                f"未知のツール: {name}（利用可能: {', '.join(TOOLS_BY_NAME)}）"
            )
        try:
            text = execute(self.world, name, args)
        except ToolError as exc:
            # ツールレベルの失敗は isError でモデルに返す（セッションは継続）。
            return _tool_error(f"Tool error: {exc}")
        finally:
            # 例外時も含め、進んだ時刻・状態を必ず保存する。
            self._save()
        return {"content": [{"type": "text", "text": text}], "isError": False}

    # ------------------------------------------------------------------ #
    # stdio ループ
    # ------------------------------------------------------------------ #
    def serve_stdio(self) -> None:
        _log("stdio サーバ開始")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                _log(f"JSON パース失敗を無視: {line[:200]!r}")
                continue
            response = self.handle_request(msg)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        _log("stdin が閉じられたため終了")


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def main() -> None:
    state_path = os.environ.get("VB_STATE_PATH")
    if not state_path:
        _log("環境変数 VB_STATE_PATH が未設定です。終了します。")
        sys.exit(2)
    seed = int(os.environ.get("VB_SEED", "0"))
    server = VBMCPServer(Path(state_path), seed=seed)
    server.serve_stdio()


if __name__ == "__main__":
    main()
