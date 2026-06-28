"""`vb-skill-run`: 強い隔離でプレイヤーをワンコマンド起動するランチャー。

Skill モード（[mcp_server.py](mcp_server.py)）を最も堅牢な形で走らせる薄いラッパ。
リポジトリ外の**中立な一時作業ディレクトリ**を作り、そこを cwd にして `claude` を
起動する。エージェントに渡すツールを `mcp__vending__*`（MCP サーバ `vending`）だけに
絞り、組み込みツール（Read/Bash/Grep 等）を `--tools ""` で全無効化するため、
ルールのソース（`env/catalog.py` 等）を物理的にもツール的にも参照できない。

使い方:
    uv run vb-skill-run --days 5
    uv run vb-skill-run --days 30 --model opus --suppliers rule --seed 7
    uv run vb-skill-run --days 5 --print-only   # 実行せず起動コマンドだけ表示
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# repo ルート: src/vending_bench/skill_run.py -> parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / ".claude" / "skills" / "vending-bench" / "SKILL.md"

START_PROMPT = (
    "Start running the vending machine business now. Follow your operating protocol: "
    "first call get_briefing, then operate using only the vending tools, sleep with "
    "wait_for_next_day after each day, and keep going until get_status reports run_finished."
)


def _skill_body() -> str:
    """SKILL.md から YAML フロントマターを除いた本文（運転プロトコル）を返す。"""
    text = SKILL_PATH.read_text(encoding="utf-8")
    if text.startswith("---"):
        # 2 つ目の '---' 以降が本文
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def _write_mcp_config(tmp_dir: Path, *, seed: int, days: int, suppliers: str,
                      save_path: str) -> Path:
    """中立 cwd からでも起動できるよう --directory 付きの一時 MCP 設定を生成する。"""
    env: dict[str, str] = {
        "VB_SEED": str(seed),
        "VB_TARGET_DAYS": str(days),
        "VB_SUPPLIERS": suppliers,
    }
    if save_path:
        env["VB_SAVE_PATH"] = save_path
    cfg = {
        "mcpServers": {
            "vending": {
                "command": "uv",
                "args": ["run", "--directory", str(PROJECT_ROOT), "vb-mcp"],
                "env": env,
            }
        }
    }
    path = tmp_dir / "vending.mcp.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def _build_command(mcp_config: Path, model: str) -> list[str]:
    return [
        "claude", "-p", START_PROMPT,
        "--append-system-prompt", _skill_body(),
        "--mcp-config", str(mcp_config),
        "--strict-mcp-config",                 # --mcp-config の MCP サーバだけを使う
        "--allowedTools", "mcp__vending__*",   # MCP ツールのみ自動許可
        "--tools", "",                         # 組み込みツールを全無効化
        "--model", model,
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Skill モードのプレイヤーを隔離環境でワンコマンド起動する")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--days", type=int, default=5, help="運転日数の上限（既定5）")
    parser.add_argument("--model", type=str, default="sonnet", help="claude のモデル")
    parser.add_argument("--suppliers", choices=["llm", "rule"], default="llm",
                        help="サプライヤー返信エンジン（既定 llm）")
    parser.add_argument("--keep-dir", action="store_true", help="一時作業ディレクトリを残す")
    parser.add_argument("--print-only", action="store_true",
                        help="実行せず、起動コマンドと一時 cwd だけ表示する")
    parser.add_argument("--save", type=str, default="",
                        help="JSON 保存先（既定: results/skill_run_seed{N}.json）")
    args = parser.parse_args()

    if not SKILL_PATH.exists():
        sys.exit(f"SKILL.md が見つかりません: {SKILL_PATH}")

    save_path = args.save or str(PROJECT_ROOT / "results" / f"skill_run_seed{args.seed}.json")

    tmp_dir = Path(tempfile.mkdtemp(prefix="vb-skill-"))
    try:
        mcp_config = _write_mcp_config(tmp_dir, seed=args.seed, days=args.days,
                                       suppliers=args.suppliers, save_path=save_path)
        cmd = _build_command(mcp_config, args.model)

        print(f"=== vb-skill-run ===", file=sys.stderr)
        print(f"作業ディレクトリ(中立 cwd): {tmp_dir}", file=sys.stderr)
        print(f"seed={args.seed} days={args.days} model={args.model} "
              f"suppliers={args.suppliers}", file=sys.stderr)
        print(f"保存先: {save_path}", file=sys.stderr)

        if args.print_only:
            print("\n# 起動コマンド（この cwd で実行）:")
            print(" ".join(_quote(c) for c in cmd))
            print(f"\n# MCP 設定: {mcp_config}")
            return

        # cwd を中立ディレクトリにして起動。出力はそのままストリームする。
        proc = subprocess.run(cmd, cwd=tmp_dir)
        sys.exit(proc.returncode)
    finally:
        if not args.keep_dir and not args.print_only:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _quote(s: str) -> str:
    return f'"{s}"' if (" " in s or s == "") else s


if __name__ == "__main__":
    main()
