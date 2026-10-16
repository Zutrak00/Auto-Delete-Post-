from __future__ import annotations

from typing import Iterator

from ..models import Post, parse_time
from .base import Field, Provider

FIELDS = "id,text,timestamp,permalink,media_type,is_quote_post"


class ThreadsProvider(Provider):
    key = "threads"
    name = "Threads"
    fields = [
        Field("access_token", "Long-lived access token", secret=True),
    ]
    setup_help = (
        "Create an app at https://developers.facebook.com with the Threads use case and the permissions "
        "threads_basic, threads_read_replies and threads_delete. Add yourself as a Threads tester, "
        "generate a user token and exchange it for a long-lived (60-day) token. The app refreshes it "
        "automatically on each run. Meta allows 100 deletes per day per account. Threads does not "
        "share like counts here, so the 'keep popular posts' rule has no effect."
    )
    delete_delay = 2.0

    api = "https://graph.threads.net/v1.0"

    def login(self) -> None:
        # Long-lived tokens last 60 days; refreshing on every run keeps them alive.
        resp = self.http.get(
            "https://graph.threads.net/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": self.cred("access_token")},
            timeout=30,
        )
        if resp.ok and resp.json().get("access_token"):
            new_token = resp.json()["access_token"]
            if new_token != self.cred("access_token"):
                self.credentials["access_token"] = new_token
                self.updated_credentials["access_token"] = new_token
        self.token = self.cred("access_token")
        self.request("GET", f"{self.api}/me", params={"fields": "id,username", "access_token": self.token})

    def iter_posts(self) -> Iterator[Post]:
        posts = list(self._listing("threads", "post")) + list(self._listing("replies", "reply"))
        posts.sort(key=lambda p: p.created_at, reverse=True)
        yield from posts

    def _listing(self, edge: str, kind: str) -> Iterator[Post]:
        url = f"{self.api}/me/{edge}"
        params: dict | None = {"fields": FIELDS, "limit": 100, "access_token": self.token}
        while url:
            data = self.request("GET", url, params=params).json()
            for item in data.get("data", []):
                # Reposts show up as facades that cannot be deleted through the API.
                if item.get("media_type") == "REPOST_FACADE":
                    continue
                yield Post(
                    id=item["id"],
                    created_at=parse_time(item["timestamp"]),
                    text=item.get("text", ""),
                    url=item.get("permalink", ""),
                    kind=kind,
                )
            # 'next' already carries every query parameter.
            url = data.get("paging", {}).get("next")
            params = None

    def delete(self, post: Post) -> None:
        self.request("DELETE", f"{self.api}/{post.id}", params={"access_token": self.token})
