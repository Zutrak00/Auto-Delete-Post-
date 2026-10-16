from __future__ import annotations

import html
import re
from typing import Iterator
from urllib.parse import urlencode

from ..models import Post, parse_time
from .base import Field, Provider

_TAGS = re.compile(r"<[^>]+>")


def strip_html(value: str) -> str:
    return html.unescape(_TAGS.sub(" ", value or "")).strip()


class MastodonProvider(Provider):
    key = "mastodon"
    name = "Mastodon"
    ease = "easy"
    ease_note = "About 1 minute: log in with your Mastodon account."
    fields = [
        Field("instance", "Instance URL", default="https://mastodon.social", help="e.g. https://mastodon.social"),
        Field("access_token", "Access token", secret=True),
    ]
    setup_help = (
        "On your instance go to Preferences → Development → New application. "
        "Tick the scopes read:accounts, read:statuses and write:statuses, save, "
        "then copy 'Your access token'."
    )

    def _base(self) -> str:
        instance = self.cred("instance").rstrip("/")
        if not instance.startswith("http"):
            instance = "https://" + instance
        return instance

    def login(self) -> None:
        self.http.headers["Authorization"] = f"Bearer {self.cred('access_token')}"
        me = self.request("GET", f"{self._base()}/api/v1/accounts/verify_credentials").json()
        self.account_id = me["id"]

    def iter_posts(self) -> Iterator[Post]:
        url = f"{self._base()}/api/v1/accounts/{self.account_id}/statuses"
        params: dict = {"limit": 40}
        while True:
            items = self.request("GET", url, params=params).json()
            if not items:
                return
            for s in items:
                if s.get("reblog"):
                    kind = "repost"
                elif s.get("in_reply_to_id"):
                    kind = "reply"
                else:
                    kind = "post"
                yield Post(
                    id=s["id"],
                    created_at=parse_time(s["created_at"]),
                    text=strip_html(s.get("content") or (s.get("reblog") or {}).get("content", "")),
                    url=s.get("url") or s.get("uri", ""),
                    likes=s.get("favourites_count", 0),
                    reposts=s.get("reblogs_count", 0),
                    pinned=bool(s.get("pinned")),
                    kind=kind,
                    extra={"reblog_id": (s.get("reblog") or {}).get("id")},
                )
            params["max_id"] = items[-1]["id"]

    def delete(self, post: Post) -> None:
        if post.kind == "repost" and post.extra.get("reblog_id"):
            self.request("POST", f"{self._base()}/api/v1/statuses/{post.extra['reblog_id']}/unreblog")
        else:
            self.request("DELETE", f"{self._base()}/api/v1/statuses/{post.id}")


# --- "Log in with Mastodon" (OAuth) ---------------------------------------------
# Every Mastodon server lets apps register themselves, so the user only needs to type their server's address.

OAUTH_SCOPES = "read:accounts read:statuses write:statuses"


def normalise_instance(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if "@" in value and not value.startswith("http"):
        # Accept a full handle like @me@mastodon.social.
        value = value.rsplit("@", 1)[-1]
    if not value:
        raise ValueError("Enter your Mastodon server, e.g. mastodon.social")
    return value if value.startswith("http") else "https://" + value


def register_app(http, instance: str, redirect_uri: str) -> dict:
    resp = http.post(f"{instance}/api/v1/apps", timeout=30, data={
        "client_name": "Auto-Delete Posts",
        "redirect_uris": redirect_uri,
        "scopes": OAUTH_SCOPES,
    })
    resp.raise_for_status()
    return resp.json()


def authorize_url(instance: str, client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                       "scope": OAUTH_SCOPES, "state": state})
    return f"{instance}/oauth/authorize?{query}"


def exchange_code(http, instance: str, client_id: str, client_secret: str, redirect_uri: str, code: str) -> tuple[str, str]:
    """Returns (access_token, @user@server)."""
    resp = http.post(f"{instance}/oauth/token", timeout=30, data={
        "grant_type": "authorization_code", "code": code, "client_id": client_id,
        "client_secret": client_secret, "redirect_uri": redirect_uri, "scope": OAUTH_SCOPES,
    })
    resp.raise_for_status()
    token = resp.json()["access_token"]
    me = http.get(f"{instance}/api/v1/accounts/verify_credentials", timeout=30,
                  headers={"Authorization": f"Bearer {token}"})
    me.raise_for_status()
    host = instance.split("://", 1)[-1]
    return token, f"@{me.json()['username']}@{host}"
