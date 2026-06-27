"""メール受信箱・送信箱。

エージェントは `send_email` で送信し、夜間にサプライヤーからの返信や各種通知が
受信箱に届く（VB: "Your email inbox refreshes automatically during the night."）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Email:
    id: int
    direction: str  # "in" (受信) | "out" (送信)
    sender: str
    recipient: str
    subject: str
    body: str
    day: int
    timestamp: str
    read: bool = False
    replied: bool = False
    """送信メールに対し、サプライヤー側が既に返信を生成したか（夜間処理用）。"""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "direction": self.direction, "sender": self.sender,
            "recipient": self.recipient, "subject": self.subject, "body": self.body,
            "day": self.day, "timestamp": self.timestamp, "read": self.read, "replied": self.replied,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Email":
        return cls(**d)


@dataclass
class Mailbox:
    messages: list[Email] = field(default_factory=list)
    next_id: int = 1

    def _new_id(self) -> int:
        i = self.next_id
        self.next_id += 1
        return i

    def add_incoming(self, *, sender: str, recipient: str, subject: str, body: str,
                     day: int, timestamp: str) -> Email:
        e = Email(id=self._new_id(), direction="in", sender=sender, recipient=recipient,
                  subject=subject, body=body, day=day, timestamp=timestamp)
        self.messages.append(e)
        return e

    def add_outgoing(self, *, sender: str, recipient: str, subject: str, body: str,
                     day: int, timestamp: str) -> Email:
        e = Email(id=self._new_id(), direction="out", sender=sender, recipient=recipient,
                  subject=subject, body=body, day=day, timestamp=timestamp, read=True)
        self.messages.append(e)
        return e

    def get(self, email_id: int) -> Email | None:
        for e in self.messages:
            if e.id == email_id:
                return e
        return None

    def inbox(self) -> list[Email]:
        return [e for e in self.messages if e.direction == "in"]

    def unread(self) -> list[Email]:
        return [e for e in self.messages if e.direction == "in" and not e.read]

    def unreplied_outgoing(self) -> list[Email]:
        return [e for e in self.messages if e.direction == "out" and not e.replied]

    def to_dict(self) -> dict:
        return {"messages": [m.to_dict() for m in self.messages], "next_id": self.next_id}

    @classmethod
    def from_dict(cls, d: dict) -> "Mailbox":
        return cls(messages=[Email.from_dict(m) for m in d.get("messages", [])],
                   next_id=d.get("next_id", 1))
