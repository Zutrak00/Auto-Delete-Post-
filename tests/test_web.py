import re
from urllib.parse import parse_qs, urlparse

import pytest
import responses

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


@responses.activate
def test_mastodon_login_flow(client):
    base = "https://m.example"
    responses.post(f"{base}/api/v1/apps", json={"client_id": "cid", "client_secret": "csec"})
    responses.post(f"{base}/oauth/token", json={"access_token": "user-token"})
    responses.get(f"{base}/api/v1/accounts/verify_credentials", json={"id": "1", "username": "alex"})

    token = csrf(client, "/accounts/new/mastodon")
    resp = client.post("/connect/mastodon", data={"csrf": token, "instance": "@alex@m.example"})
    location = resp.headers["Location"]
    assert location.startswith(f"{base}/oauth/authorize?")
    state = parse_qs(urlparse(location).query)["state"][0]

    # A callback with the wrong state is rejected and saves nothing.
    with client.session_transaction() as s:
        saved = dict(s["mastodon_oauth"])
    client.get("/connect/mastodon/callback?code=abc&state=forged")
    assert client.store.accounts() == []

    with client.session_transaction() as s:
        s["mastodon_oauth"] = saved
    resp = client.get(f"/connect/mastodon/callback?code=abc&state={state}")
    assert "/edit" in resp.headers["Location"]
    acc = client.store.accounts()[0]
    assert acc["label"] == "@alex@m.example"
    assert acc["credentials"] == {"instance": base, "access_token": "user-token"}
    assert acc["live"] is False


def test_mastodon_login_unreachable_server(client):
    token = csrf(client, "/accounts/new/mastodon")
    with responses.RequestsMock() as mock:
        mock.post("https://nope.example/api/v1/apps", status=404)
        resp = client.post("/connect/mastodon", data={"csrf": token, "instance": "nope.example"})
    assert resp.headers["Location"].endswith("/accounts/new/mastodon")


def test_healthz_is_public(monkeypatch):
    monkeypatch.setenv("AUTODELETE_PASSWORD", "pw")
    app = create_app(Store(":memory:"), start_scheduler=False)
    assert app.test_client().get("/healthz").get_data(as_text=True) == "auto-delete-posts ok"


def test_browser_network_signup_goes_to_login_page(client):
    token = csrf(client, "/accounts/new/x")
    resp = client.post("/accounts/new/x", data={"csrf": token, "cred_username": "@jack",
                                               "older_than_days": "30", "max_deletes_per_run": "100"})
    acc = client.store.accounts()[0]
    assert resp.headers["Location"].endswith(f"/accounts/{acc['id']}/login")
    assert acc["label"] == "@jack" and acc["credentials"]["username"] == "@jack"
    html = client.get(f"/accounts/{acc['id']}/login").get_data(as_text=True)
    assert "Open login window" in html and "Import archive" in html


def test_x_archive_import(client):
    import io
    import json
    import zipfile

    account_id = client.store.add_account("x", "@me", {"username": "me"}, {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("data/tweets.js", "window.YTD.tweets.part0 = " + json.dumps(
            [{"tweet": {"id_str": "1", "created_at": "Mon Jan 01 00:00:00 +0000 2018", "full_text": "hi"}}]))
    token = csrf(client, f"/accounts/{account_id}/login")
    client.post(f"/accounts/{account_id}/archive",
                data={"csrf": token, "archive": (io.BytesIO(buf.getvalue()), "twitter.zip")},
                content_type="multipart/form-data")
    assert client.store.archive_count(account_id) == 1

    client.post(f"/accounts/{account_id}/archive",
                data={"csrf": token, "archive": (io.BytesIO(b"junk"), "twitter.zip")},
                content_type="multipart/form-data")
    assert client.store.archive_count(account_id) == 1  # a bad file doesn't wipe the imported archive


def test_preview_runs_in_background(client, monkeypatch):
    import time

    from autodelete import web

    def fake_run(store, account, live, result):
        result.scanned = 3
        result.finished = True

    monkeypatch.setattr(web, "run_account", fake_run)
    account_id = client.store.add_account("mastodon", "M", {"instance": "https://m.example", "access_token": "t"}, {})
    token = csrf(client, f"/accounts/{account_id}/preview")
    client.post(f"/accounts/{account_id}/preview", data={"csrf": token})
    time.sleep(0.2)
    html = client.get(f"/accounts/{account_id}/preview").get_data(as_text=True)
    assert "posts scanned" in html and 'http-equiv="refresh"' not in html
