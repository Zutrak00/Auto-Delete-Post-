import re

import pytest

from autodelete.store import Store
from autodelete.web import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("AUTODELETE_PASSWORD", raising=False)
    store = Store(":memory:")
    app = create_app(store, start_scheduler=False)
    app.config["TESTING"] = True
    c = app.test_client()
    c.store = store
    return c


def csrf(client, path="/"):
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf" value="([0-9a-f]+)"', html)
    if match:
        return match.group(1)
    with client.session_transaction() as s:
        return s["csrf"]


def test_dashboard_lists_platforms(client):
    html = client.get("/").get_data(as_text=True)
    for name in ("Mastodon", "Bluesky", "Reddit", "X (Twitter)", "Threads", "Instagram"):
        assert name in html


def test_post_without_csrf_rejected(client):
    assert client.post("/settings", data={"interval_hours": "1"}).status_code == 400


def test_add_edit_and_go_live(client):
    token = csrf(client, "/accounts/new/mastodon")
    resp = client.post("/accounts/new/mastodon", data={
        "csrf": token, "label": "Main", "cred_instance": "https://m.example", "cred_access_token": "secret-tok",
        "older_than_days": "14", "keep_keywords": "#keep, important", "keep_pinned": "on",
        "include_replies": "on", "max_deletes_per_run": "50", "keep_if_likes_at_least": "", "enabled": "on",
    })
    assert resp.status_code == 302
    acc = client.store.accounts()[0]
    assert acc["live"] is False  # new accounts always start in preview mode
    assert acc["rules"]["older_than_days"] == 14
    assert acc["rules"]["keep_keywords"] == ["#keep", "important"]
    assert acc["rules"]["include_reposts"] is False

    # Secrets are never echoed back into the page.
    edit_html = client.get(f"/accounts/{acc['id']}/edit").get_data(as_text=True)
    assert "secret-tok" not in edit_html

    # Leaving the secret blank keeps the saved one.
    client.post(f"/accounts/{acc['id']}/edit", data={
        "csrf": token, "label": "Renamed", "cred_instance": "https://m.example", "cred_access_token": "",
        "older_than_days": "30", "max_deletes_per_run": "10",
    })
    acc = client.store.account(acc["id"])
    assert acc["label"] == "Renamed" and acc["credentials"]["access_token"] == "secret-tok"
    assert acc["enabled"] is False

    # Run now refuses while in preview mode.
    client.post(f"/accounts/{acc['id']}/run", data={"csrf": token})
    assert client.store.history() == []

    client.post(f"/accounts/{acc['id']}/mode", data={"csrf": token, "live": "1"})
    assert client.store.account(acc["id"])["live"] is True


def test_password_protection(monkeypatch):
    monkeypatch.setenv("AUTODELETE_PASSWORD", "hunter2")
    app = create_app(Store(":memory:"), start_scheduler=False)
    c = app.test_client()
    assert c.get("/").status_code == 302
    token = csrf(c, "/login")
    c.post("/login", data={"csrf": token, "password": "wrong"})
    assert c.get("/").status_code == 302
    c.post("/login", data={"csrf": token, "password": "hunter2"})
    assert c.get("/").status_code == 200


def test_schedule_settings(client):
    token = csrf(client, "/settings")
    client.post("/settings", data={"csrf": token, "interval_hours": "6"})
    assert client.store.setting("interval_hours") == "6"
    assert client.store.setting("schedule_enabled") == "0"
