"""ローカルの Claude Code CLI (`claude -p`) を補完エンドポイントとして呼ぶラッパ。

MCP は使わない。`--system-prompt` で独自のシステムプロンプトに差し替え、`--tools ""`
で組み込みツールを完全に無効化し（これをしないとモデルが本物のツールで多ターンのエージェント
ループに入り暴走してタイムアウトする）、`--json-schema` で出力を 1 アクション(1 JSON)に拘束、
`--output-format json` で結果テキストと出力トークン数を取得する。
ユーザーの subscription / OAuth 認証を使うため `--bare`（API キー強制）は使わない。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass

# 1ターン=1アクションの出力契約を CLI レベルで強制するスキーマ。
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


class ClaudeCLI:
    def __init__(self, model: str = "sonnet", timeout_s: int = 180, cwd: str | None = None):
        self.model = model
        self.timeout_s = timeout_s
        # プロジェクトの CLAUDE.md / スキルを巻き込まないよう中立な作業ディレクトリで実行
        self.cwd = cwd or tempfile.mkdtemp(prefix="vb-agent-")

    def complete(self, system_prompt: str, user_prompt: str,
                 schema: dict | None = ACTION_SCHEMA) -> LLMResponse:
        """LLM を呼び出し結果を返す。

        schema: None の場合は --json-schema を使わない（自由テキスト出力）。
                デフォルトは ACTION_SCHEMA（エージェントループ用）。
        """
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
            "--model", self.model,
        ]
        if schema is not None:
            cmd.extend(["--json-schema", json.dumps(schema)])
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
