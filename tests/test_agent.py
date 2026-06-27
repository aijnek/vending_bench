"""Phase 6: エージェントの JSON パース・メモリ・ループ（LLMをモック）のテスト。"""

from __future__ import annotations

import pytest

from vending_bench.config import EnvConfig
from vending_bench.env.world import WorldState
from vending_bench.agent.memory import ConversationMemory, parse_tool_call
from vending_bench.agent.llm import LLMResponse
from vending_bench.agent.loop import run_agent


# --------------------------------------------------------------------------- #
# パーサ
# --------------------------------------------------------------------------- #
def test_parse_plain_json():
    obj = parse_tool_call('{"thought": "go", "tool": "list_emails", "args": {}}')
    assert obj["tool"] == "list_emails" and obj["args"] == {}


def test_parse_with_code_fence_and_prose():
    text = 'Sure!\n```json\n{"tool": "set_price", "args": {"slot": "A1", "price": 2.5}}\n```'
    obj = parse_tool_call(text)
    assert obj["tool"] == "set_price" and obj["args"]["price"] == 2.5


def test_parse_missing_tool_raises():
    with pytest.raises(ValueError):
        parse_tool_call('{"args": {}}')


def test_parse_no_json_raises():
    with pytest.raises(ValueError):
        parse_tool_call("no json here")


# --------------------------------------------------------------------------- #
# メモリのトリミング
# --------------------------------------------------------------------------- #
def test_memory_trims_to_budget():
    mem = ConversationMemory(context_tokens=50)  # ~200 文字
    for i in range(100):
        mem.add_observation(f"observation number {i} " * 5)
    rendered = mem.render()
    assert len(rendered) <= 50 * 4 + 200  # 概算予算 + 1ブロック分の余裕
    assert "number 99" in rendered  # 最新は残る
    assert "number 0 " not in rendered  # 古いものは落ちる


# --------------------------------------------------------------------------- #
# ループ（モック LLM）
# --------------------------------------------------------------------------- #
class ScriptedLLM:
    """あらかじめ用意した JSON 応答を順に返すモック。"""
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        text = self._responses[self.calls] if self.calls < len(self._responses) else \
            '{"tool": "wait_for_next_day", "args": {}}'
        self.calls += 1
        return LLMResponse(text=text, output_tokens=20, cost_usd=0.0, raw={})


def test_loop_executes_scripted_actions():
    w = WorldState.new(EnvConfig(seed=1))
    llm = ScriptedLLM([
        '{"tool": "web_search", "args": {"query": "suppliers"}}',
        '{"tool": "send_email", "args": {"to": "sales@freshwholesale.com", "subject": "Order", "body": "40 x Coca-Cola 12oz can"}}',
        '{"tool": "wait_for_next_day", "args": {}}',
    ])
    summary = run_agent(w, llm, days=2, max_steps=10, memory=ConversationMemory(), verbose=False)
    # 発注メールが処理され注文が立っているはず
    assert any(o.lines for o in w.orders)
    # 出力トークンが課金対象として記録されている
    assert summary["steps"] >= 3
    assert w.ledger.transactions  # 手数料等が記録されている


def test_loop_handles_parse_errors_then_recovers():
    w = WorldState.new(EnvConfig(seed=1))
    llm = ScriptedLLM([
        "I cannot comply, here is some prose.",   # パース失敗
        '{"tool": "get_balance_and_transactions", "args": {}}',
        '{"tool": "wait_for_next_day", "args": {}}',
    ])
    summary = run_agent(w, llm, days=2, max_steps=10, memory=ConversationMemory(), verbose=False)
    assert summary["score"]["day"] >= 1  # 最終的に日送りできた
