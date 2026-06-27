"""会話履歴とコンテキスト・トリミング、ツールコールJSONの抽出。

VB の「直近Nトークンのみを入力にする」挙動を文字数予算で近似する（最新の発話を残し古い
ものを落とす）。エージェントは notes/reminders ツールで長期記憶を自分でオフロードできる。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# おおよそ 1 token ≈ 4 文字 として、履歴の文字数予算を決める
DEFAULT_CONTEXT_TOKENS = 8000
CHARS_PER_TOKEN = 4


@dataclass
class Turn:
    role: str  # "assistant" | "observation"
    text: str


@dataclass
class ConversationMemory:
    context_tokens: int = DEFAULT_CONTEXT_TOKENS
    turns: list[Turn] = field(default_factory=list)

    def add_action(self, raw_text: str) -> None:
        self.turns.append(Turn("assistant", raw_text.strip()))

    def add_observation(self, text: str) -> None:
        self.turns.append(Turn("observation", text.strip()))

    def render(self) -> str:
        """文字数予算に収まるよう、最新の発話を優先して履歴を組み立てる。"""
        budget = self.context_tokens * CHARS_PER_TOKEN
        chosen: list[str] = []
        used = 0
        for turn in reversed(self.turns):
            label = "ASSISTANT" if turn.role == "assistant" else "OBSERVATION"
            block = f"[{label}]\n{turn.text}"
            if used + len(block) > budget and chosen:
                break
            chosen.append(block)
            used += len(block)
        return "\n\n".join(reversed(chosen))


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def parse_tool_call(text: str) -> dict:
    """モデル出力から {"tool":..., "args":...} を抽出する。失敗時は ValueError。"""
    candidate = text.strip()
    m = _FENCE_RE.search(candidate)
    if m:
        candidate = m.group(1).strip()

    # 最初の '{' から対応する '}' までを取り出す
    start = candidate.find("{")
    if start == -1:
        raise ValueError("JSON オブジェクトが見つかりません")
    depth = 0
    end = -1
    for i in range(start, len(candidate)):
        c = candidate[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise ValueError("JSON オブジェクトが閉じていません")

    obj = json.loads(candidate[start:end])
    if "tool" not in obj:
        raise ValueError("'tool' フィールドがありません")
    if not isinstance(obj.get("args", {}), dict):
        raise ValueError("'args' はオブジェクトである必要があります")
    obj.setdefault("args", {})
    return obj
