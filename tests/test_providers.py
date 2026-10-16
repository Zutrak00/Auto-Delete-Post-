import json
from urllib.parse import parse_qs, urlparse

import responses
from responses import matchers

from autodelete.providers import BlueskyProvider, MastodonProvider, RedditProvider, ThreadsProvider, XProvider


@responses.activate
def test_mastodon_list_and_delete():
    base = "https://masto.example"
    responses.get(f"{base}/api/v1/accounts/verify_credentials", json={"id": "42"})
    page1 = [
        {"id": "3", "created_at": "2025-01-03T00:00:00.000Z", "content": "<p>Hello &amp; bye</p>",
         "url": f"{base}/@me/3", "favourites_count": 2, "reblogs_count": 0, "pinned": True},
        {"id": "2", "created_at": "2025-01-02T00:00:00.000Z", "content": "", "reblog": {"id": "99", "content": "<p>x</p>"}},
    ]
    page2 = [{"id": "1", "created_at": "2025-01-01T00:00:00.000Z", "content": "<p>r</p>", "in_reply_to_id": "7"}]
    responses.get(f"{base}/api/v1/accounts/42/statuses", json=page1,
                  match=[matchers.query_param_matcher({"limit": "40"})])
    responses.get(f"{base}/api/v1/accounts/42/statuses", json=page2,
                  match=[matchers.query_param_matcher({"limit": "40", "max_id": "2"})])
    responses.get(f"{base}/api/v1/accounts/42/statuses", json=[],
                  match=[matchers.query_param_matcher({"limit": "40", "max_id": "1"})])
    responses.delete(f"{base}/api/v1/statuses/3", json={})
    responses.post(f"{base}/api/v1/statuses/99/unreblog", json={})

    p = MastodonProvider({"instance": "masto.example", "access_token": "tok"})
    p.login()
    posts = list(p.iter_posts())
    assert [(x.id, x.kind) for x in posts] == [("3", "post"), ("2", "repost"), ("1", "reply")]
    assert posts[0].text == "Hello & bye" and posts[0].pinned and posts[0].likes == 2
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"
    p.delete(posts[0])
    p.delete(posts[1])


@responses.activate
def test_bluesky_list_and_delete():
    base = "https://bsky.social/xrpc"
    did = "did:plc:me"
    responses.post(f"{base}/com.atproto.server.createSession", json={"did": did, "accessJwt": "jwt"})
    responses.get(f"{base}/app.bsky.actor.getProfile", json={"pinnedPost": {"uri": f"at://{did}/app.bsky.feed.post/pin"}})
    feed = {
        "cursor": "c1",
        "feed": [
            {"post": {"uri": f"at://{did}/app.bsky.feed.post/pin", "author": {"did": did, "handle": "me.bsky.social"},
                      "record": {"text": "pinned", "createdAt": "2025-01-05T00:00:00Z"}, "likeCount": 1,
                      "indexedAt": "2025-01-05T00:00:00Z"}},
            {"post": {"uri": "at://did:plc:other/app.bsky.feed.post/o1", "author": {"did": "did:plc:other", "handle": "o"},
                      "record": {"text": "theirs", "createdAt": "2025-01-01T00:00:00Z"},
                      "viewer": {"repost": f"at://{did}/app.bsky.feed.repost/rp1"}, "indexedAt": "2025-01-01T00:00:00Z"},
             "reason": {"$type": "app.bsky.feed.defs#reasonRepost", "indexedAt": "2025-01-04T00:00:00Z"}},
        ],
    }
    feed2 = {"feed": [
        {"post": {"uri": f"at://{did}/app.bsky.feed.post/r1", "author": {"did": did, "handle": "me.bsky.social"},
                  "record": {"text": "a reply", "createdAt": "2025-01-03T00:00:00Z", "reply": {}},
                  "indexedAt": "2025-01-03T00:00:00Z"}},
    ]}
    responses.get(f"{base}/app.bsky.feed.getAuthorFeed", json=feed,
                  match=[matchers.query_param_matcher({"actor": did, "limit": "100"})])
    responses.get(f"{base}/app.bsky.feed.getAuthorFeed", json=feed2,
                  match=[matchers.query_param_matcher({"actor": did, "limit": "100", "cursor": "c1"})])
    responses.post(f"{base}/com.atproto.repo.deleteRecord", json={})

    p = BlueskyProvider({"handle": "@me.bsky.social", "app_password": "xxxx"})
    p.login()
    posts = list(p.iter_posts())
    assert [(x.kind, x.pinned) for x in posts] == [("post", True), ("repost", False), ("reply", False)]
    assert posts[1].id == f"at://{did}/app.bsky.feed.repost/rp1"
    assert posts[0].url == "https://bsky.app/profile/me.bsky.social/post/pin"
    p.delete(posts[1])
    body = json.loads(responses.calls[-1].request.body)
    assert body == {"repo": did, "collection": "app.bsky.feed.repost", "rkey": "rp1"}


@responses.activate
def test_reddit_overwrites_then_deletes():
    responses.post("https://www.reddit.com/api/v1/access_token", json={"access_token": "t"})

    def listing(children):
        return {"data": {"children": children, "after": None}}

    responses.get("https://oauth.reddit.com/user/me/submitted", json=listing([
        {"kind": "t3", "data": {"name": "t3_a", "created_utc": 1700000000, "title": "T", "selftext": "S",
                                "permalink": "/r/x/a", "score": 5, "is_self": False}},
    ]))
    responses.get("https://oauth.reddit.com/user/me/comments", json=listing([
        {"kind": "t1", "data": {"name": "t1_b", "created_utc": 1700000100, "body": "comment", "permalink": "/r/x/b", "score": 1}},
    ]))
    responses.post("https://oauth.reddit.com/api/editusertext", json={})
    responses.post("https://oauth.reddit.com/api/del", json={})

    p = RedditProvider({"client_id": "id", "client_secret": "s", "username": "me", "password": "pw"})
    p.login()
    posts = list(p.iter_posts())
    assert [x.id for x in posts] == ["t1_b", "t3_a"]  # newest first across both listings
    p.delete(posts[0])  # comment: edited then deleted
    p.delete(posts[1])  # link post: not editable, only deleted
    urls = [c.request.url for c in responses.calls[-3:]]
    assert urls == ["https://oauth.reddit.com/api/editusertext", "https://oauth.reddit.com/api/del",
                    "https://oauth.reddit.com/api/del"]


@responses.activate
def test_x_list_and_delete():
    api = "https://api.x.com/2"
    responses.get(f"{api}/users/me", json={"data": {"id": "1", "username": "me", "pinned_tweet_id": "10"}})
    responses.get(f"{api}/users/1/tweets", json={
        "data": [
            {"id": "10", "text": "pinned", "created_at": "2025-01-03T00:00:00.000Z", "public_metrics": {"like_count": 4}},
            {"id": "9", "text": "RT", "created_at": "2025-01-02T00:00:00.000Z",
             "referenced_tweets": [{"type": "retweeted", "id": "555"}]},
        ],
        "meta": {"next_token": "n1"},
    }, match=[matchers.query_param_matcher({"max_results": "100"}, strict_match=False)])
    responses.get(f"{api}/users/1/tweets", json={"data": [
        {"id": "8", "text": "@a hi", "created_at": "2025-01-01T00:00:00.000Z",
         "referenced_tweets": [{"type": "replied_to", "id": "7"}]},
    ], "meta": {}}, match=[matchers.query_param_matcher({"pagination_token": "n1"}, strict_match=False)])
    responses.delete(f"{api}/tweets/10", json={"data": {"deleted": True}})
    responses.delete(f"{api}/users/1/retweets/555", json={"data": {"retweeted": False}})

    p = XProvider({"api_key": "k", "api_secret": "s", "access_token": "t", "access_secret": "ts"})
    p.login()
    assert responses.calls[0].request.headers["Authorization"].startswith(b"OAuth ")
    posts = list(p.iter_posts())
    assert [(x.id, x.kind, x.pinned) for x in posts] == [("10", "post", True), ("9", "repost", False), ("8", "reply", False)]
    assert posts[0].likes == 4 and posts[0].url == "https://x.com/me/status/10"
    p.delete(posts[0])
    p.delete(posts[1])


@responses.activate
def test_threads_refreshes_token_and_deletes():
    api = "https://graph.threads.net/v1.0"
    responses.get("https://graph.threads.net/refresh_access_token", json={"access_token": "new-token"})
    responses.get(f"{api}/me", json={"id": "1"})
    responses.get(f"{api}/me/threads", json={
        "data": [
            {"id": "a", "text": "hello", "timestamp": "2025-01-02T00:00:00+0000", "permalink": "https://threads.net/a"},
            {"id": "rp", "timestamp": "2025-01-02T00:00:00+0000", "media_type": "REPOST_FACADE"},
        ],
        "paging": {"next": f"{api}/me/threads?after=c1&access_token=new-token"},
    }, match=[matchers.query_param_matcher({"limit": "100"}, strict_match=False)])
    responses.get(f"{api}/me/threads", json={"data": [
        {"id": "b", "text": "older", "timestamp": "2024-12-01T00:00:00+0000"},
    ]}, match=[matchers.query_param_matcher({"after": "c1"}, strict_match=False)])
    responses.get(f"{api}/me/replies", json={"data": [
        {"id": "c", "text": "reply", "timestamp": "2025-01-01T00:00:00+0000"},
    ]})
    responses.delete(f"{api}/a", json={"success": True})

    p = ThreadsProvider({"access_token": "old-token"})
    p.login()
    assert p.updated_credentials == {"access_token": "new-token"}
    posts = list(p.iter_posts())
    assert [(x.id, x.kind) for x in posts] == [("a", "post"), ("c", "reply"), ("b", "post")]
    p.delete(posts[0])
    qs = parse_qs(urlparse(responses.calls[-1].request.url).query)
    assert qs["access_token"] == ["new-token"]


@responses.activate
def test_rate_limit_is_retried(monkeypatch):
    monkeypatch.setattr("autodelete.providers.base.time.sleep", lambda s: None)
    base = "https://masto.example"
    responses.delete(f"{base}/api/v1/statuses/1", status=429, headers={"Retry-After": "1"})
    responses.delete(f"{base}/api/v1/statuses/1", json={})
    p = MastodonProvider({"instance": base, "access_token": "tok"})
    from autodelete.models import Post, parse_time

    p.delete(Post(id="1", created_at=parse_time("2025-01-01T00:00:00Z")))
    assert len(responses.calls) == 2
