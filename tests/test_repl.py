"""Phase 5: REPL の入力パースとディスパッチのスモークテスト。"""

from __future__ import annotations

import builtins

from vending_bench.config import EnvConfig
from vending_bench.cli.repl import run_repl
from vending_bench.env.world import WorldState


def _feed(monkeypatch, lines):
    it = iter(lines)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(it))


def test_repl_quoted_multiword_arg(monkeypatch, capsys):
    w = WorldState.new(EnvConfig(seed=3))
    # 倉庫に商品を入れておき、引用符付き複数語の商品名で補充できることを確認
    w.storage.add("Coca-Cola 12oz can", "small", 20, 0.66)
    _feed(monkeypatch, [
        'stock_machine A1 "Coca-Cola 12oz can" 10',
        'set_price A1 2.0',
        'get_machine_inventory',
        'quit',
    ])
    run_repl(w, state_path=None)
    out = capsys.readouterr().out
    assert "A1 [small] Coca-Cola 12oz can x10/15 @ $2.00" in out
    assert w.machine.get_slot("A1").quantity == 10


def test_repl_wait_advances_day(monkeypatch, capsys):
    w = WorldState.new(EnvConfig(seed=3))
    _feed(monkeypatch, ["wait_for_next_day", "quit"])
    run_repl(w, state_path=None)
    assert w.clock.day_index == 1
