from datetime import datetime, timedelta, timezone

import pytest

from autodelete.engine import run_account
from autodelete.models import Post, parse_time
from autodelete.providers import Provider, ProviderError
from autodelete.rules import Rules
from autodelete.store import Store

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def post(id, days_old, **kw):
    return Post(id=id, created_at=NOW - timedelta(days=days_old), **kw)


class FakeProvider(Provider):
    key = "fake"
    name = "Fake"
    fields = []

    def __init__(self, posts, fail_on=()):
        super().__init__({})
        self.posts = posts
        self.fail_on = set(fail_on)
        self.deleted = []

    def iter_posts(self):
        yield from self.posts

    def delete(self, post):
        if post.id in self.fail_on:
            raise ProviderError("boom")
        self.deleted.append(post.id)


@pytest.fixture
def store():
    return Store(":memory:")


def test_parse_time_formats():
    assert parse_time("2024-01-02T03:04:05Z") == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert parse_time("2024-01-02T03:04:05+0000") == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert parse_time("2024-01-02T03:04:05.123+02:00").hour == 1
    assert parse_time(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_rules_keep_reasons():
    rules = Rules(older_than_days=30, keep_if_likes_at_least=10, keep_keywords=["#keep"], keep_ids=["x"],
                  keep_pinned=True)
    assert rules.reason_to_keep(post("a", 5), NOW).startswith("newer than")
    assert rules.reason_to_keep(post("b", 40, likes=12), NOW) == "12 likes"
    assert rules.reason_to_keep(post("c", 40, text="Nice #KEEP"), NOW) == "contains '#keep'"
    assert rules.reason_to_keep(post("x", 400), NOW) == "on keep list"
    assert rules.reason_to_keep(post("d", 40, pinned=True), NOW) == "pinned"
    assert rules.reason_to_keep(post("e", 40, likes=3), NOW) is None

    no_replies = Rules(older_than_days=0, include_replies=False, include_reposts=False)
    assert no_replies.reason_to_keep(post("r", 1, kind="reply"), NOW) == "replies excluded"
    assert no_replies.reason_to_keep(post("s", 1, kind="repost"), NOW) == "reposts excluded"
    assert no_replies.reason_to_keep(post("t", 1, kind="comment"), NOW) is None


def test_default_rules_erase_everything():
    rules = Rules()
    for p in (post("new", 0), post("old", 400), post("pin", 1, pinned=True), post("r", 0, kind="reply"),
              post("rt", 0, kind="repost")):
        assert rules.reason_to_keep(p, NOW) is None, p.id


def test_rules_from_dict_ignores_unknown_keys():
    rules = Rules.from_dict({"older_than_days": 7, "bogus": 1})
    assert rules.older_than_days == 7


def make_account(store, live, **rules):
    account_id = store.add_account("fake", "Test", {}, Rules(**rules).to_dict(), live=live)
    return store.account(account_id)


def test_preview_never_deletes(store):
    provider = FakeProvider([post("new", 1), post("old", 100)])
    account = make_account(store, live=True, older_than_days=30)
    result = run_account(store, account, live=False, provider=provider, now=NOW)
    assert [p.id for p in result.to_delete] == ["old"]
    assert provider.deleted == []
    assert store.history() == []
    assert store.account(account["id"])["last_status"].startswith("Preview")


def test_live_run_deletes_and_logs(store):
    provider = FakeProvider([post("new", 1), post("old1", 100), post("old2", 200), post("bad", 300)], fail_on={"bad"})
    account = make_account(store, live=True, older_than_days=30)
    sleeps = []
    result = run_account(store, account, provider=provider, sleep=sleeps.append, now=NOW)
    assert provider.deleted == ["old1", "old2"]
    assert len(result.errors) == 1
    assert len(sleeps) == 2  # pause between each of the 3 delete attempts
    actions = sorted(r["action"] for r in store.history())
    assert actions == ["deleted", "deleted", "error"]
    assert store.deleted_count(account["id"]) == 2


def test_max_deletes_per_run(store):
    provider = FakeProvider([post(str(i), 100 + i) for i in range(10)])
    account = make_account(store, live=True, older_than_days=30, max_deletes_per_run=3)
    result = run_account(store, account, provider=provider, sleep=lambda s: None, now=NOW)
    assert provider.deleted == ["0", "1", "2"]
    assert result.scanned == 10


def test_login_failure_is_reported(store):
    class Broken(FakeProvider):
        def login(self):
            raise ProviderError("bad token")

    account = make_account(store, live=True)
    result = run_account(store, account, provider=Broken([]), now=NOW)
    assert result.errors == ["bad token"]
    assert store.history()[0]["action"] == "error"


def test_updated_credentials_are_saved(store):
    class Refreshing(FakeProvider):
        def login(self):
            self.updated_credentials = {"access_token": "new"}

    account_id = store.add_account("fake", "T", {"access_token": "old"}, Rules().to_dict())
    run_account(store, store.account(account_id), provider=Refreshing([]), now=NOW)
    assert store.account(account_id)["credentials"]["access_token"] == "new"


def test_missing_credentials_rejected():
    from autodelete.providers import MastodonProvider

    with pytest.raises(ProviderError, match="Access token"):
        MastodonProvider({"instance": "https://example.social"})
