---
name: play-vending-bench
description: Vending-Bench をこのセッション自身がプレイヤーとなって指定日数まで回す。14 個のシミュレーションツールだけを `vb-tool` 経由で1手ずつ叩き、純資産の最大化を目指す。`/play-vending-bench <days> [state-path]`（例 `/play-vending-bench 30`）。自販機ビジネスを自律運営してほしい・所定の日数プレイさせたいときに使う。
---

# Play Vending-Bench（セッション内プレイ）

あなた（このセッション）が **プレイヤー本人** として Vending-Bench を運営する。
`vb-tool` を介して 1 手ずつ意思決定し、自販機ビジネスを自律運営する。

## 引数
- `<days>`（必須）: 何 sim 日プレイするか。`target_day = 開始日 + <days>`。
- `[state-path]`（任意, 既定 `results/play.json`）: 状態 JSON。`results/` 配下に置くこと。

## あなたの役割と目標
- **開始時に `uv run vb-tool --state <state-path> briefing` を実行し、その出力をこの回の権威ある文脈として読み込む。**
  身元・自分のメールアドレス・倉庫/自販機の住所・発注フロー・課金/破産ルールはそこに記載されている。以下はクイック参照。
- あなたは自販機ビジネスを運営する自律 AI エージェント。会社からの支援は一切ない。
- **唯一の評価指標は純資産**（手元残高 + 機内現金 + 倉庫在庫の卸値 + 機内在庫の卸値）。未実現の見込み利益は評価されない。
- **人間ユーザーはいない。** 途中で質問して止まらず、自分の判断で最後まで回し続ける。
- 重要事実: 初期残高 $500、日次手数料 $2/日。手数料を 10 日連続で払えないと破産（terminated）。
  出力トークンは週次で $100/100万tokens 課金される（→簡潔に）。顧客はクレジット（翌日入金）か現金（要回収）で支払う。
  サプライヤーには良質・高値・詐欺（入金後未配送）がいる。支払い（`send_payment`）は**取消不可**。

## 操作機構（厳守）
- **1 手 = Bash で `vb-tool` を 1 回**。複数ツールを 1 回にまとめない。各結果を観測してから次の 1 手を決める。

  ```
  uv run vb-tool --state <state-path> --reason "<この手の思考>" <tool> '<json-args>'
  ```

  - `<json-args>` はツール引数の JSON オブジェクト（引数なしツールは省略可）。
    例: `send_email '{"to":"a@b.c","subject":"見積依頼","body":"24 x Coca-Cola 12oz can"}'`
  - **`--reason` は毎回必ず付ける。** これがトークン課金の対象（`len/4` で概算）。冗長だと週次課金が増えるので簡潔に。
- 各実行は最後に機械可読な `STATUS` 行を返す:
  `STATUS day=<d>/<total> balance=<…> machine_cash=<…> net_worth=<…> status=<running|completed|bankrupt> unread=<…> tokens_unbilled=<…>`
  毎回これを読み、`day` と `status` で停止判定する。
- **「与えられたツールだけ」を厳守**: 14 ツール経由のみ。state JSON を直接編集しない / Python で world を改変しない /
  売上モデルを迂回しない。`vb-tool tools` 以外で内部実装を触らない。

## 利用可能な 14 ツール
（一次情報は `uv run vb-tool --state <state-path> tools` で確認できる）
- `list_emails` — 受信箱一覧
- `read_email '{"email_id": <int>}'` — メール本文を読む
- `send_email '{"to","subject","body"}'` — サプライヤー等に送信（返信は翌朝）
- `web_search '{"query"}'` — サプライヤー/商品を調べる
- `get_inventory` — 倉庫在庫
- `get_machine_inventory` — 自販機スロット
- `get_balance_and_transactions '{"n": <int>}'` — 残高と取引履歴
- `send_payment '{"to","amount"}'` — 支払い（**取消不可**、未払い注文に充当）
- `stock_machine '{"slot","product","quantity"}'` — 倉庫→自販機へ補充
- `set_price '{"slot","price"}'` — スロットの販売価格設定
- `collect_cash` — 機内現金を回収して残高へ
- `set_note '{"key","text"}'` / `get_notes` — 計画用の外部メモ
- `set_reminder '{"day","text"}'` — 指定日のリマインダ
- `wait_for_next_day` — 就寝し翌朝へ。売上・配送・新着メール・週次課金を確定（**1日進める唯一の手段**）

## 進め方

### 開始時
1. `<days>` と `<state-path>` を確定。`uv run vb-tool --state <state-path> briefing` を実行し、
   出力（身元・自分のメール・倉庫/自販機住所・発注フロー・ルール）を権威あるブリーフィングとして読み込む。
2. `get_balance_and_transactions` を実行し、`STATUS` の `day` を起点として `target_day = day + <days>` を計算。
3. `set_note '{"key":"run_meta","text":"target_day=<target_day> state=<state-path>"}'` で目標を外部保存
   （コンテキスト圧縮後の復元用）。続けて `get_notes` で既存の計画があれば復元する（再開時）。
4. 初期偵察: `list_emails` / `get_inventory` / `get_machine_inventory` / `web_search` で状況把握し、初期戦略を立てる。

### 毎日のループ
- 朝のメール処理（`list_emails`→必要なら `read_email`）、サプライヤー探索・見積依頼（`send_email`）、
  入金確認の上で発注の支払い（`send_payment`）、入荷品の補充（`stock_machine`）、価格調整（`set_price`）、
  現金回収（`collect_cash`）を、その日の状況に応じて実行。
- 1 日の業務を終えたら `wait_for_next_day` で翌朝へ。`STATUS` を読んで結果を評価。
- 重要な方針・サプライヤー評価・進行中注文は `set_note` に逐次記録（外部記憶を正とする）。

### 停止条件
- `STATUS` の `day >= target_day`、または `status` が `completed` / `bankrupt` になったら **ループを終了**する。
- 終了したら最終 `STATUS` と、最終純資産・残高推移・効いた施策/失敗の要点を**簡潔に**要約報告する。
- 途中で `target_day` を見失ったら `get_notes` の `run_meta` から復元する。
