"""エージェント／人間が使うツールの定義（名前・引数・所要時間・説明）。

REPL（Phase 5）とエージェントループ（Phase 6）の両方がこの定義を共有する。
所要時間は VB に倣い 5 / 25 / 75 / 300 分の4段階。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Param:
    name: str
    type: str  # "string" | "int" | "float"
    required: bool = True
    description: str = ""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: tuple[Param, ...] = ()
    duration_min: int = 5


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("list_emails", "受信箱のメール一覧（ID・送信者・件名・未読）を表示する。", duration_min=5),
    ToolSpec("read_email", "指定IDのメール本文を読む（既読化）。", (
        Param("email_id", "int", True, "読むメールのID"),
    ), duration_min=25),
    ToolSpec("send_email", "サプライヤー等にメールを送る。返信は翌朝に届く。", (
        Param("to", "string", True, "宛先メールアドレス"),
        Param("subject", "string", True, "件名"),
        Param("body", "string", True, "本文"),
    ), duration_min=25),
    ToolSpec("web_search", "ウェブ検索。サプライヤー一覧や商品情報を調べる。", (
        Param("query", "string", False, "検索クエリ（省略可）"),
    ), duration_min=25),
    ToolSpec("get_inventory", "倉庫（storage）の在庫を表示する。", duration_min=5),
    ToolSpec("get_machine_inventory", "自販機の各スロット（商品・在庫・価格）を表示する。", duration_min=5),
    ToolSpec("get_balance_and_transactions", "残高と直近の取引履歴を表示する。", (
        Param("n", "int", False, "表示する取引件数（既定10）"),
    ), duration_min=5),
    ToolSpec("send_payment", "メール経由で支払いを行う（取消不可）。未払い注文に充当される。", (
        Param("to", "string", True, "支払先メールアドレス"),
        Param("amount", "float", True, "支払額（ドル）"),
    ), duration_min=25),
    ToolSpec("stock_machine", "倉庫から自販機スロットへ商品を補充する。", (
        Param("slot", "string", True, "スロット（例: A1）"),
        Param("product", "string", True, "商品名"),
        Param("quantity", "int", True, "補充数"),
    ), duration_min=75),
    ToolSpec("set_price", "自販機スロットの販売価格を設定する。", (
        Param("slot", "string", True, "スロット（例: A1）"),
        Param("price", "float", True, "価格（ドル）"),
    ), duration_min=5),
    ToolSpec("collect_cash", "自販機内の現金を回収して残高に入金する。", duration_min=75),
    ToolSpec("set_note", "計画用メモを保存/更新する。", (
        Param("key", "string", True, "メモのキー"),
        Param("text", "string", True, "本文"),
    ), duration_min=5),
    ToolSpec("get_notes", "保存したメモを一覧表示する。", duration_min=5),
    ToolSpec("set_reminder", "指定日に確認したいリマインダを登録する。", (
        Param("day", "int", True, "通知する day_index"),
        Param("text", "string", True, "本文"),
    ), duration_min=5),
    ToolSpec("wait_for_next_day", "業務を終え就寝。翌朝まで時間を進め、売上・配送・新着メールを確定する。", duration_min=300),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}
