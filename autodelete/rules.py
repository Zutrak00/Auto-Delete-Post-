from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from .models import Post


@dataclass
class Rules:
    """Decides which posts get deleted. Anything that matches a 'keep' rule is spared."""

    older_than_days: float = 30
    keep_if_likes_at_least: int | None = None  # spare popular posts
    keep_keywords: list[str] = field(default_factory=lambda: ["#keep"])
    keep_pinned: bool = True
    keep_ids: list[str] = field(default_factory=list)
    include_replies: bool = True
    include_reposts: bool = True
    max_deletes_per_run: int = 100

    @classmethod
    def from_dict(cls, data: dict | None) -> "Rules":
        data = data or {}
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self) -> dict:
        return asdict(self)

    def reason_to_keep(self, post: Post, now: datetime | None = None) -> str | None:
        """Return why a post is kept, or None if it should be deleted."""
        if post.id in self.keep_ids:
            return "on keep list"
        if self.keep_pinned and post.pinned:
            return "pinned"
        if post.kind == "reply" and not self.include_replies:
            return "replies excluded"
        if post.kind == "repost" and not self.include_reposts:
            return "reposts excluded"
        if post.age_days(now) < self.older_than_days:
            return f"newer than {self.older_than_days:g} days"
        if self.keep_if_likes_at_least is not None and post.likes >= self.keep_if_likes_at_least:
            return f"{post.likes} likes"
        text = post.text.lower()
        for word in self.keep_keywords:
            if word and word.lower() in text:
                return f"contains '{word}'"
        return None
