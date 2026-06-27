"""セッション運転モード（vb-session）。

`vb-run`（`claude -p` をステップ毎に新規プロセスで叩く方式）は、毎回 system prompt + 履歴 +
次アクション指示を送り直し、かつプロセスが毎回新規なのでプロンプトキャッシュが効かない。
そのためトークン消費が大きく、長期間（数十日〜）のシミュレーションが現実的でない。

本モードは代わりに **1 つの Claude Code エージェントセッション** を起動し、環境ツールを
ネイティブな tool use として呼ばせる。1 セッション内では system prompt と増えていく
トランスクリプトがキャッシュされるため、ステップあたりのトークン効率が大きく改善する。

秘匿性: 環境本体は別プロセスの MCP サーバ（`mcp/server.py`）に閉じ込められ、エージェントには
ツールのスキーマと結果しか見えない。さらに:
- 中立な一時 cwd で実行し、ソースを含むディレクトリを `--add-dir` しない。
- `--strict-mcp-config` で外部 MCP を読み込まない。
- `--allowedTools` を本環境の MCP ツール（mcp__vb__*）だけに限定する。-p モードでは許可外の
  ツール（Bash/Read 等）は自動拒否されるため、エージェントはファイルやソースを覗けない。

オーケストレータは短いラウンドに分けてセッションを `--resume` で継続し（キャッシュは維持）、
各ラウンドの実出力トークンを sim 内台帳に課金する。これにより「セッション方式は本当に
長く回せるのか（=安いのか）」を、in-sim のトークンコストにも反映した形で確認できる。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ..config import EnvConfig
from ..env.world import WorldState
from ..scoring import score_breakdown
from ..tools.schema import TOOLS
from .prompts import (
    SESSION_CONTINUE_INSTRUCTION,
    SESSION_START_INSTRUCTION,
    session_system_prompt,
)

# このパッケージ（src ディレクトリ）。MCP サーバ子プロセスへ PYTHONPATH として渡す。
_SRC_DIR = Path(__file__).resolve().parents[2]

ALLOWED_TOOLS = [f"mcp__vb__{t.name}" for t in TOOLS]


class SessionError(RuntimeError):
    pass


def _mcp_config(state_path: Path, seed: int) -> dict:
    """vb MCP サーバを起動するための --mcp-config を組み立てる。"""
    env = dict(os.environ)
    env["VB_STATE_PATH"] = str(state_path.resolve())
    env["VB_SEED"] = str(seed)
    # claude が env を置換しても import できるよう PYTHONPATH を明示する。
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SRC_DIR) + (os.pathsep + existing if existing else "")
    return {
        "mcpServers": {
            "vb": {
                "command": sys.executable,
                "args": ["-m", "vending_bench.mcp.server"],
                "env": env,
            }
        }
    }


def _run_claude(
    *,
    prompt: str,
    model: str,
    mcp_config: dict,
    max_turns: int,
    timeout_s: int,
    cwd: str,
    system_prompt: str | None = None,
    resume_session_id: str | None = None,
) -> dict:
    """claude を1ラウンド実行し、--output-format json をパースして返す。"""
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--mcp-config",
        json.dumps(mcp_config),
        "--strict-mcp-config",
        "--allowedTools",
        ",".join(ALLOWED_TOOLS),
        "--disable-slash-commands",
        "--output-format",
        "json",
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "default",
    ]
    if system_prompt is not None:
        cmd += ["--system-prompt", system_prompt]
    if resume_session_id is not None:
        cmd += ["--resume", resume_session_id]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd
        )
    except subprocess.TimeoutExpired as exc:
        raise SessionError(f"claude がタイムアウトしました（{timeout_s}s）") from exc

    if proc.returncode != 0:
        raise SessionError(
            f"claude が失敗しました (rc={proc.returncode}): {proc.stderr.strip()[:500]}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SessionError(
            f"claude が非JSONを返しました: {proc.stdout.strip()[:500]}"
        ) from exc
    return data


def _output_tokens(data: dict) -> int:
    usage = data.get("usage") or {}
    return int(usage.get("output_tokens", 0) or 0)


def run_session(
    *,
    state_path: Path,
    days: int,
    seed: int,
    model: str,
    turns_per_round: int,
    max_rounds: int,
    timeout_s: int,
    verbose: bool = True,
) -> dict:
    """セッションをラウンド分割で駆動し、目標日数/破産/上限まで運転する。"""
    # 初期 world を用意（MCP サーバも同じ state ファイルを読む）。
    if state_path.exists():
        world = WorldState.load(state_path)
        if verbose:
            print(f"既存 state をロード: {state_path} (day {world.clock.day_index})")
    else:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        world = WorldState.new(EnvConfig(seed=seed))
        world.save(state_path)

    sys_prompt = session_system_prompt(world.config)
    target_day = world.clock.day_index + days
    mcp_config = _mcp_config(state_path, seed)
    cwd = tempfile.mkdtemp(prefix="vb-session-")

    session_id: str | None = None
    total_output_tokens = 0
    total_cost_usd = 0.0
    rounds = 0
    stale_rounds = 0  # 日が進まないラウンドの連続数

    while rounds < max_rounds:
        rounds += 1
        first = session_id is None
        prompt = SESSION_START_INSTRUCTION if first else SESSION_CONTINUE_INSTRUCTION
        day_before = world.clock.day_index

        try:
            data = _run_claude(
                prompt=prompt,
                model=model,
                mcp_config=mcp_config,
                max_turns=turns_per_round,
                timeout_s=timeout_s,
                cwd=cwd,
                system_prompt=sys_prompt if first else None,
                resume_session_id=session_id,
            )
        except SessionError as exc:
            print(f"[round {rounds}] {exc}")
            break

        session_id = data.get("session_id") or session_id
        round_tokens = _output_tokens(data)
        total_output_tokens += round_tokens
        total_cost_usd += float(data.get("total_cost_usd", 0.0) or 0.0)

        # MCP サーバが保存した最新 state を読み直し、実出力トークンを sim へ課金する。
        world = WorldState.load(state_path)
        world.ledger.record_output_tokens(round_tokens)
        world.save(state_path)

        advanced = world.clock.day_index - day_before
        if verbose:
            print(
                f"[round {rounds} | day {world.clock.day_index}/{target_day} | "
                f"${world.ledger.balance:.2f} | +{round_tokens} tok | turns={data.get('num_turns')}] "
                f"net=${world.net_worth():.2f} status={world.status}"
            )

        if world.is_terminal:
            if verbose:
                print(f"シミュレーション終了: {world.status}")
            break
        if world.clock.day_index >= target_day:
            if verbose:
                print("目標日数に到達しました。")
            break

        stale_rounds = stale_rounds + 1 if advanced == 0 else 0
        if stale_rounds >= 3:
            print("3 ラウンド連続で日が進みませんでした。エージェントが停止したとみなし中断します。")
            break

    summary = {
        "mode": "session",
        "rounds": rounds,
        "score": score_breakdown(world),
        "session_output_tokens": total_output_tokens,
        "session_cost_usd": round(total_cost_usd, 4),
    }
    world.save(state_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vending-Bench 風シミュレーション: 単一 Claude Code セッションで自動運転"
    )
    parser.add_argument("--days", type=int, default=5, help="運転する sim 日数（既定5）")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", type=str, default="haiku", help="claude のモデル（haiku/sonnet/opus 等）")
    parser.add_argument(
        "--state", type=Path, default=Path("results/session.json"), help="状態の保存先（途中保存・再開も可）"
    )
    parser.add_argument(
        "--turns-per-round", type=int, default=40, help="1 ラウンド(=1 claude 呼び出し)の最大ツール往復数"
    )
    parser.add_argument(
        "--max-rounds", type=int, default=None, help="安全上限のラウンド数（既定 days*3+5）"
    )
    parser.add_argument("--timeout", type=int, default=600, help="claude 1ラウンドのタイムアウト秒")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    max_rounds = args.max_rounds if args.max_rounds is not None else args.days * 3 + 5

    print(
        f"=== セッション運転開始: {args.days}日 / 最大{max_rounds}ラウンド / "
        f"model={args.model} / turns/round={args.turns_per_round} ==="
    )
    summary = run_session(
        state_path=args.state,
        days=args.days,
        seed=args.seed,
        model=args.model,
        turns_per_round=args.turns_per_round,
        max_rounds=max_rounds,
        timeout_s=args.timeout,
        verbose=not args.quiet,
    )
    print("\n=== 結果 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
