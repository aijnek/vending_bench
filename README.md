# Vending-Bench 2 風シミュレーション環境

[Vending-Bench 2 (Andon Labs)](https://andonlabs.com/evals/vending-bench-2) を模した、
「1年間の自販機ビジネスをエージェントが運営する」シミュレーション環境の自作実装。

## 概要

- **期間**: 365日間、初期残高 $500
- **目標**: 純資産（= 残高 + 機内現金 + 在庫評価 + 機内在庫評価）を最大化
- **コスト**: 日次手数料 $2/日 + 出力トークン $100/100万トークン（週次課金）
- **終了条件**: 365日完了 or 手数料未払い10日連続（破産）

## 構成

```
src/vending_bench/
├── config.py            # EnvConfig（全パラメータ）
├── scoring.py           # net worth 計算・複数ラン集計
├── env/
│   ├── world.py         # WorldState（全状態の集約・日送り・永続化）
│   ├── clock.py         # SimClock
│   ├── ledger.py        # 財務台帳（残高・取引履歴・クレジット入金）
│   ├── machine.py       # VendingMachine（スロット・現金・価格）
│   ├── storage.py       # 倉庫在庫
│   ├── mailbox.py       # メールボックス（受信・送信）
│   ├── orders.py        # 発注管理（配送待ち）
│   ├── sales.py         # 需要モデル・売上シミュレーション
│   ├── events.py        # 夜間イベント（配送到着・メール・返金）
│   ├── weather.py       # 天候
│   └── suppliers/
│       ├── base.py      # SupplierProfile / NegotiationEngine プロトコル
│       ├── catalog.py   # サプライヤー定義・商品マスタ
│       ├── rule_based.py # ルールベース交渉エンジン（フォールバック）
│       └── llm_based.py  # LLM 駆動交渉エンジン（デフォルト）
├── tools/
│   ├── schema.py        # ツールスキーマ定義
│   └── api.py           # ツール実処理（execute）
├── cli/
│   ├── repl.py          # 人間操作 REPL（vb-play）
│   └── tool.py          # ワンショット ツール実行 CLI（vb-tool）
└── agent/
    ├── loop.py          # エージェントループ（vb-run）
    ├── llm.py           # Claude Code CLI ラッパ（claude -p）
    ├── memory.py        # 会話履歴管理（コンテキスト長トリミング）
    └── prompts.py       # システムプロンプト
```

## 利用可能ツール（エージェント・REPL 共通）

| ツール | 説明 |
|--------|------|
| `list_emails` | 受信箱の一覧 |
| `read_email` | メールを読む |
| `send_email` | メールを送る |
| `web_search` | サプライヤーディレクトリを検索 |
| `get_inventory` | 倉庫在庫の確認 |
| `get_machine_inventory` | 自販機スロットの確認 |
| `get_balance_and_transactions` | 残高・取引履歴 |
| `send_payment` | 支払い |
| `stock_machine` | 倉庫から自販機へ補充 |
| `set_price` | スロット価格を設定 |
| `collect_cash` | 機内現金を回収 |
| `set_note` / `get_notes` | メモの保存・取得 |
| `set_reminder` | リマインダ登録 |
| `wait_for_next_day` | 翌日へ進む（日次売上・配送・手数料を処理） |

## 使い方

```bash
uv sync                              # 依存をインストール
uv run pytest                        # テスト実行

uv run vb-play                       # 人間が手動操作（REPL）

uv run vb-run --days 5               # エージェントに5日間自動運転させる（サプライヤーは LLM）
uv run vb-run --days 365 --model haiku  # 365日フルラン（results/run.json に途中保存）
uv run vb-run --days 5 --rule-based-suppliers  # サプライヤーをルールベースに切り替え
```

## セッション内プレイ（`/play-vending-bench` skill / `vb-tool`）

`vb-run` がエージェントを別プロセスで自動運転するのに対し、`/play-vending-bench` skill は
**Claude Code セッション自身がプレイヤー**となって 14 ツールを 1 手ずつ叩く。橋渡しが `vb-tool` で、
1 プロセス = 1 ツール実行。状態は `--state` の JSON に load/save され、結果文字列＋機械可読な `STATUS`
フッタを出力する（state は `vb-run` と同形式の WorldState ダンプ）。

```bash
uv run vb-tool --state results/play.json tools        # 14 ツールの一覧
uv run vb-tool --state results/play.json briefing      # ビジネス文脈ブリーフィング（claude -p の system prompt と同一情報）
uv run vb-tool --state results/play.json --reason "翌朝へ" wait_for_next_day
uv run vb-tool --state results/play.json send_email '{"to":"a@b.c","subject":"s","body":"b"}'
```

- `briefing` … 身元・メール・住所・発注フロー・課金/破産ルールを `agent/prompts.py` の `business_briefing`
  から生成して出力（`system_prompt` と共通の single source of truth）。skill 開始時に読み込む。
- `--reason TEXT` … この手の思考。長さ ÷ 4 で出力トークンを概算し、週次課金に積む（`claude -p` 版を再現）。
- `--supplier-engine {llm,rule}` … サプライヤー返信エンジン。既定 `llm`（haiku＝`vb-run` と同じ）、
  `rule` で決定的・追加 API 呼び出しなし。

state JSON は `vb-run` と同形式なので、プレイ後に同じスクリプトで可視化できる:

```bash
uv run python scripts/visualize_runs.py results -o results/play_balance.png
```

## `vb-run` オプション

| オプション | 既定値 | 説明 |
|------------|--------|------|
| `--days` | 5 | 運転するシミュレーション日数 |
| `--max-steps` | days × 60 | 安全上限のステップ数 |
| `--model` | `sonnet` | `claude` に渡すモデル名 |
| `--seed` | 0 | 乱数シード（再現性） |
| `--state` | `results/run.json` | 状態の保存先（途中保存・再開も可） |
| `--context-tokens` | 8000 | 会話履歴の概算トークン上限 |
| `--timeout` | 180 | `claude` 1呼び出しのタイムアウト（秒） |
| `--quiet` | false | ステップログを抑制 |
| `--rule-based-suppliers` | false | サプライヤー返信をルールベースエンジンで生成（デフォルトは LLM エンジン） |

## サプライヤーエンジン

エージェントがサプライヤーにメールを送ると、交渉エンジンが返信を生成する。

### LLM エンジン（デフォルト）

`LLMNegotiationEngine`（`env/suppliers/llm_based.py`）が `claude haiku` を使って
各サプライヤーのペルソナに沿った自然な返信を生成する。

- **1回の LLM 呼び出し**で「意図・注文商品/数量・特急要否・返信文」を構造化 JSON として抽出
- **価格・発注はエンジン側が正本**として確定（LLM は返信文の生成に専念）
- **LLM 失敗時**はルールベースエンジンへ自動フォールバック
- **無限交渉防止**: 交渉ラウンドを最大 6 回でクランプし、価格下限到達時はペルソナ内で固辞

### サプライヤー類型と特急配送サーチャージ

| 類型 | 説明 | 特急サーチャージ | 配送短縮 |
|------|------|-----------------|---------|
| `friendly` | 正直・初回から良心的価格 | +10% | あり |
| `negotiating` | 正直・交渉で値下げ | +15% | あり |
| `scam` | 高値をふっかけ・ほぼ譲らない | +25%（課金するが速くならない） | なし |
| `bait_and_switch` | 好条件で釣り・支払い後に届けない | +5%（どのみち届かない） | なし |

### ルールベースエンジン

`--rule-based-suppliers` フラグで切り替え。決定論的な返信生成（API 不要）。
テストや再現実験に適している。

## エージェントの実装メモ

エージェントは Claude Code CLI（`claude -p`）をサブプロセスとして呼ぶ自前ループ。
MCP は使わず、ユーザーの subscription/OAuth 認証を流用する（`--bare` 不使用）。

暴走防止のため以下を設定している:
- `--tools ""` で組み込みツールを完全に無効化
- `--json-schema` で出力を 1 アクション（JSON オブジェクト）に拘束
- `--strict-mcp-config` + `--disable-slash-commands` で外部連携を遮断
- `--effort low` でレイテンシ優先
