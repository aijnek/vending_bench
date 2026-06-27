"""ツールの実処理。WorldState を操作する唯一の API。

REPL もエージェントループもここを呼ぶ。各ツールは文字列の結果を返し、`execute` が
スキーマに基づく引数検証・型変換・時間進行をまとめて行う。
"""

from __future__ import annotations

from typing import Any

from ..env import events as events_mod
from ..env import sales as sales_mod
from ..env.suppliers.catalog import web_search_directory
from ..env.world import MorningReport, WorldState
from .schema import TOOLS_BY_NAME


class ToolError(Exception):
    """引数不正などツール呼び出しの失敗。"""


# --------------------------------------------------------------------------- #
# 表示ヘルパ
# --------------------------------------------------------------------------- #
def _render_machine(world: WorldState) -> str:
    lines = [f"自販機（現金 ${world.machine.cash:.2f}）:"]
    for s in world.machine.slots:
        if s.is_empty:
            lines.append(f"  {s.label} [{s.size_class}] 空 (容量{s.capacity})")
        else:
            lines.append(f"  {s.label} [{s.size_class}] {s.product_name} x{s.quantity}/{s.capacity} "
                         f"@ ${s.price:.2f}")
    return "\n".join(lines)


def _render_storage(world: WorldState) -> str:
    if not world.storage.items:
        return "倉庫は空です。"
    lines = ["倉庫在庫:"]
    for it in world.storage.items.values():
        lines.append(f"  {it.name} [{it.size}] x{it.quantity} (単価 ${it.unit_cost:.2f})")
    lines.append(f"  在庫評価額: ${world.storage.value():.2f}")
    return "\n".join(lines)


def _render_morning(world: WorldState, rep: MorningReport) -> str:
    s = rep.sales
    lines = [
        f"=== Day {rep.day} ({rep.date}) の朝 ===",
        f"前日の売上: {s.units_sold} 個 / ${s.revenue_total:.2f}"
        + (f"  内訳: {s.per_item}" if s.per_item else ""),
        f"日次手数料: {'支払済' if rep.fee_paid else '★未払い（資金不足）'}",
    ]
    if rep.credits_settled:
        lines.append(f"クレジット入金: ${rep.credits_settled:.2f}")
    if rep.tokens_billed:
        lines.append(f"トークン課金: -${rep.tokens_billed:.2f}")
    if rep.overnight.deliveries:
        lines.append("配送到着: " + "; ".join(rep.overnight.deliveries))
    lines.append(f"新着メール: {rep.overnight.new_email_count} 件（未読 {len(world.mailbox.unread())} 件）")
    due = [r for r in world.reminders if not r.get("done") and r.get("day", 0) <= rep.day]
    for r in due:
        lines.append(f"🔔 リマインダ: {r['text']}")
        r["done"] = True
    lines.append(f"残高: ${world.ledger.balance:.2f} / 純資産: ${world.net_worth():.2f} / 状態: {world.status}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# ツール本体
# --------------------------------------------------------------------------- #
def list_emails(world: WorldState) -> str:
    inbox = world.mailbox.inbox()
    if not inbox:
        return "受信箱は空です。"
    lines = [f"受信箱（{len(inbox)} 件, 未読 {len(world.mailbox.unread())} 件）:"]
    for e in inbox:
        mark = " " if e.read else "*"
        lines.append(f"  [{mark}] #{e.id} from {e.sender} — {e.subject} (day {e.day})")
    return "\n".join(lines)


def read_email(world: WorldState, email_id: int) -> str:
    e = world.mailbox.get(email_id)
    if e is None or e.direction != "in":
        return f"ID {email_id} の受信メールは見つかりません。"
    e.read = True
    return (f"ID: {e.id}\nFrom: {e.sender}\nTo: {e.recipient}\nDay: {e.day}\n"
            f"Subject: {e.subject}\n\n{e.body}")


def send_email(world: WorldState, to: str, subject: str, body: str) -> str:
    world.mailbox.add_outgoing(sender=world.config.agent_email, recipient=to,
                               subject=subject, body=body, day=world.clock.day_index,
                               timestamp=world.timestamp)
    return f"メールを {to} に送信しました（返信は翌朝以降に届きます）。"


def web_search(world: WorldState, query: str = "") -> str:
    header = f"検索: {query}\n\n" if query else ""
    return header + web_search_directory()


def get_inventory(world: WorldState) -> str:
    return _render_storage(world)


def get_machine_inventory(world: WorldState) -> str:
    return _render_machine(world)


def get_balance_and_transactions(world: WorldState, n: int = 10) -> str:
    pending = round(sum(c.amount for c in world.ledger.pending_credits), 2)
    lines = [
        f"残高: ${world.ledger.balance:.2f}",
        f"未入金クレジット: ${pending:.2f} / 機内現金: ${world.machine.cash:.2f}",
        f"純資産: ${world.net_worth():.2f}",
        f"直近 {n} 件の取引:",
    ]
    for t in world.ledger.transactions[-n:]:
        lines.append(f"  day{t.day} {t.kind:>22} {t.amount:+9.2f} -> ${t.balance_after:.2f}  {t.description}")
    return "\n".join(lines)


def send_payment(world: WorldState, to: str, amount: float) -> str:
    amount = round(float(amount), 2)
    if amount <= 0:
        return "支払額は正の値にしてください。"
    if not world.ledger.can_afford(amount):
        return f"残高不足のため支払えません（残高 ${world.ledger.balance:.2f} < ${amount:.2f}）。"
    world.ledger.post(kind="purchase", amount=-amount, day=world.clock.day_index,
                      timestamp=world.timestamp, description=f"支払い -> {to}")
    ok, msg = events_mod.register_payment(world, to, amount)
    return f"${amount:.2f} を {to} に支払いました。\n{msg}"


def stock_machine(world: WorldState, slot: str, product: str, quantity: int) -> str:
    item = world.storage.items.get(product)
    if item is None:
        return f"倉庫に「{product}」がありません。get_inventory で在庫名を確認してください。"
    available = item.quantity
    desired = min(int(quantity), available)
    if desired <= 0:
        return f"「{product}」の在庫が不足しています（在庫 {available}）。"
    added, msg = world.machine.stock(slot, product_name=product, size=item.size,
                                     quantity=desired, unit_cost=item.unit_cost)
    if added > 0:
        world.storage.remove(product, added)
    return msg


def set_price(world: WorldState, slot: str, price: float) -> str:
    ok, msg = world.machine.set_price(slot, float(price))
    return msg


def collect_cash(world: WorldState) -> str:
    amount = world.machine.collect_cash()
    if amount <= 0:
        return "機内に回収できる現金はありません。"
    world.ledger.post(kind="sale_cash_collected", amount=amount, day=world.clock.day_index,
                      timestamp=world.timestamp, description="自販機現金の回収")
    return f"自販機から ${amount:.2f} を回収し、残高に入金しました（残高 ${world.ledger.balance:.2f}）。"


def set_note(world: WorldState, key: str, text: str) -> str:
    world.notes[key] = text
    return f"メモ「{key}」を保存しました。"


def get_notes(world: WorldState) -> str:
    if not world.notes:
        return "メモはありません。"
    return "メモ:\n" + "\n".join(f"  [{k}] {v}" for k, v in world.notes.items())


def set_reminder(world: WorldState, day: int, text: str) -> str:
    world.reminders.append({"day": int(day), "text": text, "done": False})
    return f"day {day} のリマインダを登録しました。"


def wait_for_next_day(world: WorldState) -> str:
    rep = world.advance_to_next_day(sales_fn=sales_mod.simulate_day,
                                    overnight_fn=events_mod.process_overnight)
    return _render_morning(world, rep)


_DISPATCH = {
    "list_emails": list_emails, "read_email": read_email, "send_email": send_email,
    "web_search": web_search, "get_inventory": get_inventory,
    "get_machine_inventory": get_machine_inventory,
    "get_balance_and_transactions": get_balance_and_transactions,
    "send_payment": send_payment, "stock_machine": stock_machine, "set_price": set_price,
    "collect_cash": collect_cash, "set_note": set_note, "get_notes": get_notes,
    "set_reminder": set_reminder, "wait_for_next_day": wait_for_next_day,
}

_COERCE = {"int": int, "float": float, "string": str}


def _coerce_args(spec, args: dict) -> dict:
    out: dict[str, Any] = {}
    for p in spec.params:
        if p.name in args and args[p.name] is not None and args[p.name] != "":
            try:
                out[p.name] = _COERCE[p.type](args[p.name])
            except (ValueError, TypeError) as exc:
                raise ToolError(f"引数 {p.name} は {p.type} である必要があります: {args[p.name]!r}") from exc
        elif p.required:
            raise ToolError(f"必須引数が不足しています: {p.name}")
    return out


def execute(world: WorldState, name: str, args: dict | None = None) -> str:
    """ツールを実行し、結果文字列を返す。スキーマに基づき引数検証と時間進行を行う。"""
    args = args or {}
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        raise ToolError(f"未知のツール: {name}（利用可能: {', '.join(TOOLS_BY_NAME)}）")
    if world.is_terminal:
        return f"シミュレーションは終了しています（状態: {world.status}）。これ以上操作できません。"

    kwargs = _coerce_args(spec, args)
    result = _DISPATCH[name](world, **kwargs)

    if name != "wait_for_next_day":
        world.clock.advance_within_day(spec.duration_min)
    return result
