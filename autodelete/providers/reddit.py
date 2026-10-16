from __future__ import annotations

from typing import Iterator

from ..models import Post, parse_time
from .base import Field, Provider, ProviderError

OVERWRITE_TEXT = "[deleted]"


class RedditProvider(Provider):
    key = "reddit"
    name = "Reddit"
    fields = [
        Field("client_id", "App client ID", help="The string under 'personal use script'"),
        Field("client_secret", "App secret", secret=True),
        Field("username", "Reddit username"),
        Field("password", "Reddit password", secret=True),
        Field(
            "overwrite_first",
            "Overwrite text before deleting (yes/no)",
            required=False,
            default="yes",
            help="Edits comments/self-posts to '[deleted]' first so archive sites keep nothing useful.",
        ),
    ]
    setup_help = (
        "Go to https://www.reddit.com/prefs/apps → 'create another app', choose 'script', "
        "redirect URI http://localhost:8080. Copy the client ID (under the app name) and secret. "
        "Accounts with two-factor auth must append ':<6-digit code>' to the password, so a "
        "non-2FA account works best for scheduled runs."
    )
    delete_delay = 1.2

    api = "https://oauth.reddit.com"

    def login(self) -> None:
        token = self.request(
            "POST",
            "https://www.reddit.com/api/v1/access_token",
            auth=(self.cred("client_id"), self.cred("client_secret")),
            data={"grant_type": "password", "username": self.cred("username"), "password": self.cred("password")},
        ).json()
        if "access_token" not in token:
            raise ProviderError(f"Reddit login failed: {token.get('error', 'unknown error')}")
        self.http.headers["Authorization"] = f"bearer {token['access_token']}"

    def iter_posts(self) -> Iterator[Post]:
        user = self.cred("username")
        # Fetch both listings, then merge newest-first.
        posts = list(self._listing(f"/user/{user}/submitted")) + list(self._listing(f"/user/{user}/comments"))
        posts.sort(key=lambda p: p.created_at, reverse=True)
        yield from posts

    def _listing(self, path: str) -> Iterator[Post]:
        params: dict = {"limit": 100, "sort": "new", "raw_json": 1}
        while True:
            data = self.request("GET", self.api + path, params=params).json()["data"]
            for child in data.get("children", []):
                d = child["data"]
                is_comment = child["kind"] == "t1"
                yield Post(
                    id=d["name"],
                    created_at=parse_time(d["created_utc"]),
                    text=d.get("body") if is_comment else f"{d.get('title', '')}\n{d.get('selftext', '')}".strip(),
                    url="https://www.reddit.com" + d.get("permalink", ""),
                    likes=d.get("score", 0),
                    pinned=bool(d.get("pinned")),
                    kind="comment" if is_comment else "post",
                    extra={"editable": is_comment or bool(d.get("is_self"))},
                )
            if not data.get("after"):
                return
            params["after"] = data["after"]

    def delete(self, post: Post) -> None:
        if self.cred("overwrite_first").lower() in ("yes", "y", "true", "1") and post.extra.get("editable"):
            self.request("POST", f"{self.api}/api/editusertext", data={"thing_id": post.id, "text": OVERWRITE_TEXT})
        self.request("POST", f"{self.api}/api/del", data={"id": post.id})
