from __future__ import annotations

import hmac
import os
import secrets
import threading
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from .engine import run_account
from .providers import PROVIDERS, UNSUPPORTED
from .rules import Rules
from .scheduler import Scheduler, next_run
from .store import Store


def create_app(store: Store | None = None, start_scheduler: bool = True) -> Flask:
    app = Flask(__name__)
    store = store or Store()
    # Keep the session key in the database so logins survive restarts.
    secret = os.environ.get("AUTODELETE_SECRET_KEY") or store.setting("secret_key")
    if not secret:
        secret = secrets.token_hex(32)
        store.set_setting("secret_key", secret)
    app.secret_key = secret
    app.config["STORE"] = store
    password = os.environ.get("AUTODELETE_PASSWORD", "")

    if start_scheduler:
        app.config["SCHEDULER"] = Scheduler(store)
        app.config["SCHEDULER"].start()

    # --- security helpers ------------------------------------------------------
    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def protect():
        if request.method == "POST":
            sent = request.form.get("csrf", "")
            expected = session.get("csrf", "")
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400, "Form expired, go back and try again.")
        if password and not session.get("authed") and request.endpoint not in ("login", "static"):
            return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not password:
            return redirect(url_for("index"))
        if request.method == "POST":
            if hmac.compare_digest(request.form.get("password", ""), password):
                session["authed"] = True
                return redirect(url_for("index"))
            flash("Wrong password", "error")
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # --- pages -----------------------------------------------------------------
    @app.get("/")
    def index():
        accounts = store.accounts()
        for acc in accounts:
            acc["platform_name"] = PROVIDERS[acc["platform"]].name if acc["platform"] in PROVIDERS else acc["platform"]
            acc["deleted_total"] = store.deleted_count(acc["id"])
        return render_template(
            "index.html",
            accounts=accounts,
            providers=PROVIDERS,
            unsupported=UNSUPPORTED,
            next_run=next_run(store),
            interval=store.setting("interval_hours"),
        )

    @app.route("/accounts/new/<platform>", methods=["GET", "POST"])
    def new_account(platform):
        provider = PROVIDERS.get(platform) or abort(404)
        if request.method == "POST":
            creds = _credentials_from_form(provider, {})
            rules = _rules_from_form()
            label = request.form.get("label", "").strip() or provider.name
            account_id = store.add_account(platform, label, creds, rules.to_dict(),
                                           live=False, enabled="enabled" in request.form)
            flash("Account added in Preview mode. Run a preview to check what would be deleted, "
                  "then switch it to Live.", "ok")
            return redirect(url_for("preview", account_id=account_id))
        return render_template("account_form.html", provider=provider, account=None, rules=Rules())

    @app.route("/accounts/<int:account_id>/edit", methods=["GET", "POST"])
    def edit_account(account_id):
        account = store.account(account_id) or abort(404)
        provider = PROVIDERS[account["platform"]]
        if request.method == "POST":
            store.update_account(
                account_id,
                label=request.form.get("label", "").strip() or provider.name,
                credentials=_credentials_from_form(provider, account["credentials"]),
                rules=_rules_from_form().to_dict(),
                enabled="enabled" in request.form,
            )
            flash("Saved.", "ok")
            return redirect(url_for("index"))
        return render_template("account_form.html", provider=provider, account=account,
                               rules=Rules.from_dict(account["rules"]))

    @app.post("/accounts/<int:account_id>/delete")
    def remove_account(account_id):
        store.delete_account(account_id)
        flash("Account removed. Its saved credentials were deleted.", "ok")
        return redirect(url_for("index"))

    @app.post("/accounts/<int:account_id>/mode")
    def set_mode(account_id):
        store.account(account_id) or abort(404)
        live = request.form.get("live") == "1"
        store.update_account(account_id, live=live)
        flash("Live mode on: matching posts will really be deleted on the next run." if live
              else "Back in Preview mode: nothing will be deleted.", "ok")
        return redirect(url_for("index"))

    @app.route("/accounts/<int:account_id>/preview", methods=["GET", "POST"])
    def preview(account_id):
        account = store.account(account_id) or abort(404)
        result = None
        if request.method == "POST":
            result = run_account(store, account, live=False)
        return render_template("preview.html", account=account, result=result,
                               provider=PROVIDERS[account["platform"]])

    @app.post("/accounts/<int:account_id>/run")
    def run_now(account_id):
        account = store.account(account_id) or abort(404)
        if not account["live"]:
            flash("This account is in Preview mode. Switch it to Live to delete posts.", "error")
            return redirect(url_for("index"))
        threading.Thread(target=run_account, args=(store, account), kwargs={"live": True}, daemon=True).start()
        flash("Deletion started in the background. Refresh History to follow progress.", "ok")
        return redirect(url_for("history", account=account_id))

    @app.get("/history")
    def history():
        account_id = request.args.get("account", type=int)
        return render_template("history.html", rows=store.history(500, account_id),
                               account=store.account(account_id) if account_id else None)

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        if request.method == "POST":
            store.set_setting("schedule_enabled", "1" if "schedule_enabled" in request.form else "0")
            try:
                hours = max(float(request.form.get("interval_hours", "24")), 0.25)
            except ValueError:
                hours = 24
            store.set_setting("interval_hours", f"{hours:g}")
            flash("Schedule saved.", "ok")
            return redirect(url_for("settings"))
        return render_template("settings.html", enabled=store.setting("schedule_enabled") == "1",
                               interval=store.setting("interval_hours"), next_run=next_run(store))

    return app


def _credentials_from_form(provider, existing: dict) -> dict:
    creds = dict(existing)
    for f in provider.fields:
        value = request.form.get(f"cred_{f.name}", "").strip()
        # Secret fields are never shown again; leaving them blank keeps the saved value.
        if f.secret and not value and existing.get(f.name):
            continue
        creds[f.name] = value or f.default
    return creds


def _rules_from_form() -> Rules:
    form = request.form

    def number(name, default, cast=float):
        try:
            return cast(form.get(name, "").strip())
        except ValueError:
            return default

    likes = form.get("keep_if_likes_at_least", "").strip()
    return Rules(
        older_than_days=max(number("older_than_days", 30), 0),
        keep_if_likes_at_least=int(likes) if likes.isdigit() else None,
        keep_keywords=[w.strip() for w in form.get("keep_keywords", "").split(",") if w.strip()],
        keep_pinned="keep_pinned" in form,
        keep_ids=[w.strip() for w in form.get("keep_ids", "").replace("\n", ",").split(",") if w.strip()],
        include_replies="include_replies" in form,
        include_reposts="include_reposts" in form,
        max_deletes_per_run=max(number("max_deletes_per_run", 100, int), 1),
    )
