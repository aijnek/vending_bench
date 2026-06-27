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
│   └── suppliers/       # サプライヤーカタログ・ルールベース応答
├── tools/
│   ├── schema.py        # ツールスキーマ定義
│   └── api.py           # ツール実処理（execute）
├── cli/
│   └── repl.py          # 人間操作 REPL（vb-play）
├── mcp/
│   └── server.py        # 依存ゼロ stdio MCP サーバ（セッション運転モード用）
└── agent/
    ├── loop.py          # ステップ毎 claude -p ループ（vb-run）
    ├── session.py       # 単一セッション運転オーケストレータ（vb-session）
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

uv run vb-run --days 5               # エージェントに5日間自動運転させる（ステップ毎 claude -p 方式）
uv run vb-run --days 365 --model haiku  # 365日フルラン（results/run.json に途中保存）

uv run vb-session --days 30 --model haiku  # 単一セッション運転（プロンプトキャッシュが効く方式）
```

## 2つの運転方式

| | `vb-run`（loop.py） | `vb-session`（session.py） |
|---|---|---|
| 呼び出し | **ステップ毎**に `claude -p` を新規プロセスで起動 | **単一セッション**を `--resume` でラウンド継続 |
| 入力 | 毎回 system prompt + 履歴 + 次アクション指示を再送 | system prompt は初回のみ。以降はセッションが文脈を保持 |
| プロンプトキャッシュ | プロセスが毎回新規なので**効かない** | セッション内でキャッシュが**効く**（出力に `cache_read_input_tokens`） |
| ツール | 無効化し、出力 JSON を手動パースして `execute` | **MCP ツール**としてネイティブに tool use |
| 想定用途 | 1ターン1JSON の厳密制御・短期検証 | トークン効率重視・長期間の運転 |

`vb-run` は毎ステップで文脈を丸ごと再課金・再処理するため、haiku でもトークン消費が大きく
長期間（数十日〜）の運転が現実的でなかった。`vb-session` は 1 セッション内で system prompt と
トランスクリプトがキャッシュされるため、ステップあたりのトークン効率が改善する。

### `vb-session` の仕組みと秘匿性

環境本体（`WorldState` とサプライヤー/天候/需要などの全ルール）は、別プロセスの **MCP サーバ**
（`src/vending_bench/mcp/server.py`）に閉じ込められる。エージェント（Claude Code セッション）に
見えるのは **MCP ツールのスキーマ（名前・説明・引数）とツール結果、そして system prompt だけ**で、
環境の「答え」は一切露出しない。これを次の多層で担保している:

- 中立な一時ディレクトリで実行し、ソースを含むディレクトリを `--add-dir` しない。
- `--strict-mcp-config` で外部 MCP を読み込まない。
- `--allowedTools` を本環境の MCP ツール（`mcp__vb__*`）だけに限定する。`-p` モードでは許可外の
  ツール（Bash/Read 等）は自動拒否されるため、エージェントはファイルやソースを覗けない。

オーケストレータ（`session.py`）はセッションを短いラウンドに分けて `--resume` で継続し
（キャッシュは維持される）、目標日数・破産・無進捗のいずれかに達するまで運転する。各ラウンドの
**実出力トークン数**を sim 内台帳に課金するため、キャッシュによるコスト削減が in-sim の
トークンコストにも反映される。

| オプション | 既定値 | 説明 |
|------------|--------|------|
| `--days` | 5 | 運転するシミュレーション日数 |
| `--model` | `haiku` | `claude` に渡すモデル名 |
| `--state` | `results/session.json` | 状態の保存先（途中保存・再開も可） |
| `--turns-per-round` | 40 | 1 ラウンド（=1 `claude` 呼び出し）の最大ツール往復数 |
| `--max-rounds` | days×3+5 | 安全上限のラウンド数 |
| `--seed` | 0 | 乱数シード |
| `--timeout` | 600 | `claude` 1ラウンドのタイムアウト（秒） |

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

## エージェントの実装メモ

両方式とも Claude Code CLI（`claude -p`）をサブプロセスとして呼び、ユーザーの
subscription/OAuth 認証を流用する（`--bare` 不使用）。

### `vb-run`（ステップ毎方式）

MCP は使わず、ステップ毎に新規プロセスで `claude -p` を起動する自前ループ。暴走防止のため:
- `--tools ""` で組み込みツールを完全に無効化
- `--json-schema` で出力を 1 アクション（JSON オブジェクト）に拘束
- `--strict-mcp-config` + `--disable-slash-commands` で外部連携を遮断
- `--effort low` でレイテンシ優先

### `vb-session`（単一セッション方式）

環境ツールを MCP サーバ（`mcp/server.py`）として公開し、単一セッションでネイティブに
tool use させる。`--strict-mcp-config` + `--allowedTools "mcp__vb__*"` のみ許可 + 中立 cwd で、
エージェントには「使えるツールと system prompt」だけが見えるようにしている（環境内部は秘匿）。
セッションを `--resume` で継続するためプロンプトキャッシュが効き、ステップあたりのトークン効率が高い。
