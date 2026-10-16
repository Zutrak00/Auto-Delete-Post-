import io
import json
import zipfile
from datetime import datetime, timezone

import pytest

from autodelete.engine import run_account
from autodelete.models import Post
from autodelete.providers import Provider
from autodelete.providers.instagram import parse_posts
from autodelete.providers.x_browser import archive_item_to_post, parse_archive, parse_timeline
from autodelete.rules import Rules
from autodelete.store import Store

ME = "1001"


def tweet(id, text, user=ME, when="Wed Oct 10 20:19:24 +0000 2018", **extra):
    return {"legacy": {"id_str": id, "created_at": when, "full_text": text, "user_id_str": user,
                       "favorite_count": 3, "retweet_count": 1, **extra}}


def test_parse_x_timeline_response():
    # Shaped like X's UserTweetsAndReplies response.
    payload = {"data": {"user": {"result": {"rest_id": ME, "legacy": {"pinned_tweet_ids_str": ["1"]}, "timeline_v2": {
        "timeline": {"instructions": [
            {"type": "TimelinePinEntry", "entry": {"content": {"itemContent": {
                "tweet_results": {"result": {"__typename": "Tweet", **tweet("1", "pinned!")}}}}}},
            {"type": "TimelineAddEntries", "entries": [
                {"content": {"itemContent": {"tweet_results": {"result": {
                    "__typename": "TweetWithVisibilityResults", "tweet": tweet("2", "hello")}}}}},
                {"content": {"itemContent": {"tweet_results": {"result": tweet(
                    "3", "RT @other: theirs",
                    retweeted_status_result={"result": tweet("900", "theirs", user="55")})}}}},
                {"content": {"items": [
                    {"item": {"itemContent": {"tweet_results": {"result": tweet("901", "question?", user="55")}}}},
                    {"item": {"itemContent": {"tweet_results": {"result": tweet(
                        "4", "@other answer", in_reply_to_status_id_str="901")}}}},
                ]}},
            ]},
        ]}}}}}}
    posts, pinned = parse_timeline(payload, ME, "me")
    by_id = {p.id: p for p in posts}
    assert set(by_id) == {"1", "2", "3", "4"}  # other people's posts are ignored
    assert pinned == {"1"}
    assert by_id["3"].kind == "repost" and by_id["4"].kind == "reply" and by_id["2"].kind == "post"
    assert by_id["2"].created_at == datetime(2018, 10, 10, 20, 19, 24, tzinfo=timezone.utc)
    assert by_id["2"].likes == 3 and by_id["2"].url == "https://x.com/me/status/2"


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_parse_x_archive_zip():
    part0 = "window.YTD.tweets.part0 = " + json.dumps([
        {"tweet": {"id_str": "10", "created_at": "Mon Jan 01 00:00:00 +0000 2018", "full_text": "old post",
                   "favorite_count": "7"}},
        {"tweet": {"id_str": "11", "created_at": "Mon Jan 01 00:00:00 +0000 2018", "full_text": "RT @a: x"}},
    ])
    part1 = "window.YTD.tweets.part1 = " + json.dumps([
        {"tweet": {"id_str": "12", "created_at": "Mon Jan 01 00:00:00 +0000 2018", "full_text": "@a hi",
                   "in_reply_to_status_id_str": "5"}},
    ])
    data = _zip({"data/tweets.js": part0, "data/tweets-part1.js": part1, "data/like.js": "[]",
                 "data/tweets_media/x.jpg": "img"})
    items = parse_archive(data, "twitter-2026.zip")
    assert [(i["id"], i["kind"], i["likes"]) for i in items] == [("10", "post", 7), ("11", "repost", 0), ("12", "reply", 0)]
    post = archive_item_to_post(items[0], "me", pinned={"10"})
    assert post.pinned and post.created_at.year == 2018

    # The bare tweets.js file works too.
    assert len(parse_archive(part0.encode(), "tweets.js")) == 2


def test_parse_x_archive_rejects_wrong_file():
    with pytest.raises(ValueError, match="zip"):
        parse_archive(b"not a zip", "archive.zip")
    with pytest.raises(ValueError, match="No posts"):
        parse_archive(_zip({"data/like.js": "[]"}), "archive.zip")


def test_parse_instagram_profile_response():
    # Shaped like the profile feed query Instagram's website makes.
    payload = {"data": {"xdt_api__v1__feed__user_timeline_graphql_connection": {"edges": [
        {"node": {"code": "ABC", "pk": "1", "taken_at": 1700000000, "like_count": 12,
                  "caption": {"text": "beach day"}, "user": {"username": "Me", "pk": "77"},
                  "timeline_pinned_user_ids": [77]}},
        {"node": {"code": "DEF", "pk": "2", "taken_at": 1600000000, "caption": None,
                  "owner": {"id": "77"}}},
        {"node": {"code": "XYZ", "pk": "3", "taken_at": 1600000000, "user": {"username": "someoneelse", "pk": "9"}}},
    ]}}}
    posts = {p.id: p for p in parse_posts(payload, "me", user_id="77")}
    assert set(posts) == {"ABC", "DEF"}
    assert posts["ABC"].pinned and posts["ABC"].likes == 12 and posts["ABC"].text == "beach day"
    assert posts["DEF"].text == "" and posts["DEF"].url.endswith("/p/DEF/")


class FakeBrowserProvider(Provider):
    key = "fake"
    name = "Fake"
    fields = []
    max_per_run = 2

    def __init__(self, posts):
        super().__init__({})
        self.posts, self.deleted, self.closed = posts, [], False

    def iter_posts(self):
        yield from self.posts

    def delete(self, post):
        self.deleted.append(post.id)

    def close(self):
        self.closed = True


def test_engine_caps_runs_prunes_archive_and_closes_browser():
    store = Store(":memory:")
    account_id = store.add_account("x", "X", {"username": "me"}, Rules(older_than_days=1).to_dict(), live=True)
    store.set_archive(account_id, [{"id": str(i), "created_at": "2018-01-01T00:00:00+00:00"} for i in range(5)])
    old = datetime(2018, 1, 1, tzinfo=timezone.utc)
    provider = FakeBrowserProvider([Post(id=str(i), created_at=old) for i in range(5)])
    result = run_account(store, store.account(account_id), provider=provider, sleep=lambda s: None)
    assert provider.deleted == ["0", "1"]  # provider's safety cap beats the rule's 100
    assert provider.closed and result.finished
    assert sorted(i["id"] for i in store.archive(account_id)) == ["2", "3", "4"]
