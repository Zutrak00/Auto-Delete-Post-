from __future__ import annotations

from typing import Iterator

from requests_oauthlib import OAuth1

from ..models import Post, parse_time
from .base import Field, Provider


class TumblrProvider(Provider):
    key = "tumblr"
    name = "Tumblr"
    fields = [
        Field("blog", "Blog name", help="e.g. myblog (from myblog.tumblr.com)"),
        Field("consumer_key", "OAuth consumer key"),
        Field("consumer_secret", "OAuth consumer secret", secret=True),
        Field("token", "OAuth token"),
        Field("token_secret", "OAuth token secret", secret=True),
    ]
    setup_help = (
        "Register an app at https://www.tumblr.com/oauth/apps (any website and callback URL work, e.g. "
        "http://localhost:8080). Then open https://api.tumblr.com/console, enter the app's consumer key and "
        "secret, allow access, and click 'Show keys' to copy the token and token secret."
    )

    api = "https://api.tumblr.com/v2"

    def _blog(self) -> str:
        blog = self.cred("blog").removeprefix("https://").removeprefix("http://").strip("/")
        return blog if "." in blog else f"{blog}.tumblr.com"

    def login(self) -> None:
        self.http.auth = OAuth1(
            self.cred("consumer_key"), self.cred("consumer_secret"), self.cred("token"), self.cred("token_secret")
        )
        self.request("GET", f"{self.api}/blog/{self._blog()}/info")

    def iter_posts(self) -> Iterator[Post]:
        offset = 0
        while True:
            data = self.request(
                "GET", f"{self.api}/blog/{self._blog()}/posts",
                params={"offset": offset, "limit": 20, "reblog_info": "true"},
            ).json()["response"]
            posts = data.get("posts", [])
            if not posts:
                return
            for p in posts:
                yield Post(
                    id=p.get("id_string") or str(p["id"]),
                    created_at=parse_time(p["timestamp"]),
                    text=p.get("summary") or p.get("title") or "",
                    url=p.get("post_url", ""),
                    likes=p.get("note_count", 0),
                    pinned=bool(p.get("is_pinned")),
                    kind="repost" if p.get("reblogged_from_id") else "post",
                )
            offset += len(posts)

    def delete(self, post: Post) -> None:
        self.request("POST", f"{self.api}/blog/{self._blog()}/post/delete", data={"id": post.id})
