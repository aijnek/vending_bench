# Vending-Bench 2 風シミュレーション環境

[Vending-Bench 2 (Andon Labs)](https://andonlabs.com/evals/vending-bench-2) を模した、
「1年間の自販機ビジネスをエージェントが運営する」シミュレーション環境の自作実装。

## 構成

- **環境コア** (`src/vending_bench/env/`): 決定論的な状態機械（時刻・残高・在庫・自販機・メール・売上・天候・サプライヤー）。
- **ツール層** (`src/vending_bench/tools/`): エージェント／人間が世界を操作する唯一のAPI。
- **人間操作 REPL** (`src/vending_bench/cli/`): 手動で環境を動かし挙動を確認する。
- **エージェント** (`src/vending_bench/agent/`): ローカル `claude -p` を補完エンドポイントとして呼ぶ自前ループ。

## 使い方

```bash
uv sync                 # 依存をインストール
uv run pytest           # テスト
uv run vb-play          # 人間が手動操作（REPL）
uv run vb-run --days 30 # エージェントに自動運転させる
```

詳細な開発プランは作業中。
