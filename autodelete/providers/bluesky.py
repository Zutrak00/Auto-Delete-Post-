from __future__ import annotations

from typing import Iterator

from ..models import Post, parse_time
from .base import Field, Provider, ProviderError


def split_at_uri(uri: str) -> tuple[str, str, str]:
    """at://did:plc:abc/app.bsky.feed.post/3k... -> (repo, collection, rkey)"""
    if not uri.startswith("at://"):
        raise ProviderError(f"Not an AT URI: {uri}")
    parts = uri[len("at://"):].split("/")
    if len(parts) != 3:
        raise ProviderError(f"Unexpected AT URI: {uri}")
    return parts[0], parts[1], parts[2]


class BlueskyProvider(Provider):
    key = "bluesky"
    name = "Bluesky"
    ease = "easy"
    ease_note = "About 2 minutes: just make an app password."
    fields = [
        Field("handle", "Handle", help="e.g. you.bsky.social"),
        Field("app_password", "App password", secret=True),
        Field("service", "PDS / service URL", required=False, default="https://bsky.social"),
    ]
    setup_help = (
        "In Bluesky open Settings → Privacy and security → App passwords → Add App Password. "
        "Use that password here, never your main password."
    )

    def _base(self) -> str:
        return self.cred("service").rstrip("/")

    def login(self) -> None:
        session = self.request(
            "POST",
            f"{self._base()}/xrpc/com.atproto.server.createSession",
            json={"identifier": self.cred("handle").lstrip("@"), "password": self.cred("app_password")},
        ).json()
        self.did = session["did"]
        self.http.headers["Authorization"] = f"Bearer {session['accessJwt']}"
        profile = self.request(
            "GET", f"{self._base()}/xrpc/app.bsky.actor.getProfile", params={"actor": self.did}
        ).json()
        self.pinned_uri = (profile.get("pinnedPost") or {}).get("uri")

    def iter_posts(self) -> Iterator[Post]:
        params: dict = {"actor": self.did, "limit": 100}
        while True:
            data = self.request("GET", f"{self._base()}/xrpc/app.bsky.feed.getAuthorFeed", params=params).json()
            for item in data.get("feed", []):
                post = item["post"]
                reason = (item.get("reason") or {}).get("$type", "")
                record = post.get("record", {})
                if reason.endswith("#reasonRepost"):
                    repost_uri = (post.get("viewer") or {}).get("repost")
                    if not repost_uri:
                        continue
                    yield Post(
                        id=repost_uri,
                        created_at=parse_time(item["reason"].get("indexedAt") or post["indexedAt"]),
                        text=record.get("text", ""),
                        url=_web_url(post),
                        kind="repost",
                    )
                    continue
                if post.get("author", {}).get("did") != self.did:
                    continue
                yield Post(
                    id=post["uri"],
                    created_at=parse_time(record.get("createdAt") or post["indexedAt"]),
                    text=record.get("text", ""),
                    url=_web_url(post),
                    likes=post.get("likeCount", 0),
                    reposts=post.get("repostCount", 0),
                    pinned=post["uri"] == self.pinned_uri,
                    kind="reply" if "reply" in record else "post",
                )
            cursor = data.get("cursor")
            if not cursor or not data.get("feed"):
                return
            params["cursor"] = cursor

    def delete(self, post: Post) -> None:
        repo, collection, rkey = split_at_uri(post.id)
        self.request(
            "POST",
            f"{self._base()}/xrpc/com.atproto.repo.deleteRecord",
            json={"repo": repo, "collection": collection, "rkey": rkey},
        )


def _web_url(post: dict) -> str:
    handle = post.get("author", {}).get("handle", "")
    rkey = post["uri"].rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"
