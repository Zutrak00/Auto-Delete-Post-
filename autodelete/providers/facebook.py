from __future__ import annotations

from typing import Iterator

from ..models import Post, parse_time
from .base import Field, Provider

GRAPH = "https://graph.facebook.com/v23.0"
FIELDS = "id,message,story,created_time,permalink_url,reactions.summary(total_count).limit(0)"


class FacebookPageProvider(Provider):
    key = "facebook_page"
    name = "Facebook Page"
    ease = "advanced"
    ease_note = "Needs a Meta developer app. Pages only."
    fields = [
        Field("page_token", "Page access token", secret=True),
    ]
    setup_help = (
        "Works for Facebook Pages you manage, not personal profiles. Create an app at "
        "https://developers.facebook.com, open the Graph API Explorer, select your Page and request "
        "pages_show_list, pages_read_engagement and pages_manage_posts. Exchange the user token for a "
        "long-lived one, then call /me/accounts with it: the Page token returned there does not expire."
    )

    def login(self) -> None:
        self.token = self.cred("page_token")
        self.request("GET", f"{GRAPH}/me", params={"fields": "id,name", "access_token": self.token})

    def iter_posts(self) -> Iterator[Post]:
        url = f"{GRAPH}/me/posts"
        params: dict | None = {"fields": FIELDS, "limit": 100, "access_token": self.token}
        while url:
            data = self.request("GET", url, params=params).json()
            for item in data.get("data", []):
                yield Post(
                    id=item["id"],
                    created_at=parse_time(item["created_time"]),
                    text=item.get("message") or item.get("story") or "",
                    url=item.get("permalink_url", ""),
                    likes=(item.get("reactions") or {}).get("summary", {}).get("total_count", 0),
                )
            # 'next' already carries every query parameter.
            url = data.get("paging", {}).get("next")
            params = None

    def delete(self, post: Post) -> None:
        self.request("DELETE", f"{GRAPH}/{post.id}", params={"access_token": self.token})
