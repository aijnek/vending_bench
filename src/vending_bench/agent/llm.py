"""LLM バックエンドラッパ。

現在サポートするバックエンド:
  - ClaudeCLI  : `claude -p` (Claude Code CLI) を補完エンドポイントとして使用。
  - CursorCLI  : `cursor -p` (Cursor CLI) を補完エンドポイントとして使用。

ClaudeCLI は `--json-schema` で出力を 1 アクション(1 JSON)に拘束し、`--tools ""` で
組み込みツールを完全に無効化する。`--output-format json` で結果テキストと出力トークン数を取得。

CursorCLI は `--json-schema` / `--output-format json` / `--tools ""` 等の Claude 固有フラグを
サポートしない。JSON 強制はシステムプロンプトの OUTPUT CONTRACT に依存し、
テキスト出力からの JSON 抽出は parse_tool_call (memory.py) で行う。
出力トークン数・コストは取得できないため 0 として返す。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Protocol

# 1ターン=1アクションの出力契約を CLI レベルで強制するスキーマ(ClaudeCLI 専用)。
# これを渡さないと、履歴を会話形式で与えているため haiku 等が「続きの会話全体」を
# 自分でロールプレイし始め（偽の観測結果まで捏造して何ターンも生成）、max_tokens まで
# 暴走出力してタイムアウトする。--json-schema で出力を 1 オブジェクトに拘束して防ぐ。
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "tool": {"type": "string"},
        "args": {"type": "object"},
    },
    "required": ["tool", "args"],
    "additionalProperties": False,
}


@dataclass
class LLMResponse:
    text: str
    output_tokens: int
    cost_usd: float
    raw: dict


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    """LLM バックエンドの共通インターフェース。"""

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse: ...


class ClaudeCLI:
    """ローカルの Claude Code CLI (`claude -p`) を補完エンドポイントとして呼ぶラッパ。

    MCP は使わない。`--system-prompt` で独自のシステムプロンプトに差し替え、`--tools ""`
    で組み込みツールを完全に無効化し（これをしないとモデルが本物のツールで多ターンのエージェント
    ループに入り暴走してタイムアウトする）、`--json-schema` で出力を 1 アクション(1 JSON)に拘束、
    `--output-format json` で結果テキストと出力トークン数を取得する。
    ユーザーの subscription / OAuth 認証を使うため `--bare`（API キー強制）は使わない。
    """

    def __init__(self, model: str = "sonnet", timeout_s: int = 180, cwd: str | None = None):
        self.model = model
        self.timeout_s = timeout_s
        # プロジェクトの CLAUDE.md / スキルを巻き込まないよう中立な作業ディレクトリで実行
        self.cwd = cwd or tempfile.mkdtemp(prefix="vb-agent-")

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        cmd = [
            "claude", "-p", user_prompt,
            "--system-prompt", system_prompt,
            "--output-format", "json",
            # 組み込みツールを完全に外す。`--allowedTools none` は許可リストに "none" という
            # ツール名を足すだけで実際にはツールが残り、モデルが本物のツール(WebSearch等)で
            # 多ターンのエージェントループに入って暴走 → タイムアウトしていた。`--tools ""` で全無効化。
            "--tools", "",
            "--strict-mcp-config",          # 外部 MCP サーバを読み込まない
            "--disable-slash-commands",     # スキル解決を無効化
            "--effort", "low",              # グローバルの effortLevel 設定を上書き
            "--json-schema", json.dumps(ACTION_SCHEMA),  # 出力を1アクション(1 JSON)に拘束
            "--model", self.model,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.timeout_s, cwd=self.cwd)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"claude CLI timed out after {self.timeout_s}s") from exc

        if proc.returncode != 0:
            raise LLMError(f"claude CLI failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}")

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"claude CLI returned non-JSON: {proc.stdout.strip()[:500]}") from exc

        if data.get("is_error"):
            raise LLMError(f"claude CLI error: {data.get('result', '')[:500]}")

        usage = data.get("usage", {})
        return LLMResponse(
            text=data.get("result", ""),
            output_tokens=int(usage.get("output_tokens", 0)),
            cost_usd=float(data.get("total_cost_usd", 0.0)),
            raw=data,
        )


class CursorCLI:
    """Cursor CLI (`cursor -p`) を補完エンドポイントとして呼ぶラッパ。

    Claude CLI と異なり以下の点が変わる:
      - コマンド       : `cursor` を使用
      - ツール制限     : `--no-tools` で組み込みツールを無効化
                         (`--tools ""` / `--allowedTools` は Claude 固有)
      - JSON 強制      : `--json-schema` 非対応のため、プロンプトの OUTPUT CONTRACT に依存。
                         出力テキストからの JSON 抽出は parse_tool_call (memory.py) が担う。
      - 出力フォーマット: `--output-format json` 非対応。stdout は平文テキスト。
      - トークン数/コスト: 取得不可のため 0 として返す(sim 内の課金は発生しない)。
    """

    def __init__(self, model: str = "claude-4-sonnet", timeout_s: int = 180, cwd: str | None = None):
        self.model = model
        self.timeout_s = timeout_s
        self.cwd = cwd or tempfile.mkdtemp(prefix="vb-agent-")

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        cmd = [
            "cursor", "-p", user_prompt,
            "--system-prompt", system_prompt,
            "--no-tools",   # 組み込みツールを無効化(cursor CLI のフラグ)
            "--model", self.model,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.timeout_s, cwd=self.cwd)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"cursor CLI timed out after {self.timeout_s}s") from exc

        if proc.returncode != 0:
            raise LLMError(f"cursor CLI failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}")

        text = proc.stdout.strip()
        if not text:
            raise LLMError("cursor CLI returned empty output")

        # Cursor は JSON ラッパを返さず平文テキストを返す。
        # parse_tool_call がマークダウンフェンスや埋め込み JSON を抽出するため
        # ここではテキストをそのまま返す。
        return LLMResponse(
            text=text,
            output_tokens=0,  # Cursor CLI は出力トークン数を返さない
            cost_usd=0.0,
            raw={"result": text},
        )


def create_llm(agent: str, model: str, timeout_s: int) -> ClaudeCLI | CursorCLI:
    """エージェントバックエンドを選択して LLM インスタンスを返す。

    Args:
        agent: バックエンド種別。"claude" または "cursor"。
        model: モデル名。バックエンドに応じた名前を渡す。
        timeout_s: 1 呼び出しのタイムアウト秒。
    """
    if agent == "claude":
        return ClaudeCLI(model=model, timeout_s=timeout_s)
    if agent == "cursor":
        return CursorCLI(model=model, timeout_s=timeout_s)
    raise ValueError(f"未知のエージェントバックエンド: {agent!r} (claude / cursor を指定)")
