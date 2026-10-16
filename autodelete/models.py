from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Post:
    """A single post as returned by a provider, normalised across platforms."""

    id: str
    created_at: datetime
    text: str = ""
    url: str = ""
    likes: int = 0
    reposts: int = 0
    pinned: bool = False
    kind: str = "post"  # post, reply, repost, comment
    extra: dict = field(default_factory=dict)

    def age_days(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.created_at).total_seconds() / 86400


def parse_time(value: str | int | float) -> datetime:
    """Parse ISO-8601 strings or unix timestamps into an aware UTC datetime."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    # Threads returns offsets like +0000 without a colon.
    if len(value) > 5 and value[-5] in "+-" and value[-4:].isdigit():
        value = value[:-2] + ":" + value[-2:]
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
