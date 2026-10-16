from __future__ import annotations

from typing import Iterator

from requests_oauthlib import OAuth1

from ..models import Post, parse_time
from .base import Field, Provider


class XProvider(Provider):
    key = "x"
    name = "X (Twitter)"
    ease = "advanced"
    ease_note = "Needs a paid X developer plan."
    fields = [
        Field("api_key", "API key (consumer key)"),
        Field("api_secret", "API key secret", secret=True),
        Field("access_token", "Access token"),
        Field("access_secret", "Access token secret", secret=True),
    ]
    setup_help = (
        "Create a project and app at https://developer.x.com. In the app's 'User authentication settings' "
        "set permissions to 'Read and write', then under 'Keys and tokens' generate the API key/secret and "
        "an Access token/secret for your own account. Reading your timeline needs a paid API plan, and the "
        "API only returns your most recent ~3,200 posts."
    )

    api = "https://api.x.com/2"

    def login(self) -> None:
        self.http.auth = OAuth1(
            self.cred("api_key"),
            self.cred("api_secret"),
            self.cred("access_token"),
            self.cred("access_secret"),
        )
        me = self.request("GET", f"{self.api}/users/me", params={"user.fields": "pinned_tweet_id,username"}).json()
        self.user_id = me["data"]["id"]
        self.username = me["data"].get("username", "")
        self.pinned_id = me["data"].get("pinned_tweet_id")

    def iter_posts(self) -> Iterator[Post]:
        params: dict = {
            "max_results": 100,
            "tweet.fields": "created_at,public_metrics,referenced_tweets",
        }
        while True:
            data = self.request("GET", f"{self.api}/users/{self.user_id}/tweets", params=params).json()
            for t in data.get("data", []):
                refs = {r["type"]: r["id"] for r in t.get("referenced_tweets", [])}
                if "retweeted" in refs:
                    kind = "repost"
                elif "replied_to" in refs:
                    kind = "reply"
                else:
                    kind = "post"
                metrics = t.get("public_metrics", {})
                yield Post(
                    id=t["id"],
                    created_at=parse_time(t["created_at"]),
                    text=t.get("text", ""),
                    url=f"https://x.com/{self.username or 'i'}/status/{t['id']}",
                    likes=metrics.get("like_count", 0),
                    reposts=metrics.get("retweet_count", 0),
                    pinned=t["id"] == self.pinned_id,
                    kind=kind,
                    extra={"source_id": refs.get("retweeted")},
                )
            token = data.get("meta", {}).get("next_token")
            if not token:
                return
            params["pagination_token"] = token

    def delete(self, post: Post) -> None:
        if post.kind == "repost" and post.extra.get("source_id"):
            self.request("DELETE", f"{self.api}/users/{self.user_id}/retweets/{post.extra['source_id']}")
        else:
            self.request("DELETE", f"{self.api}/tweets/{post.id}")
