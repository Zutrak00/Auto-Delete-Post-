from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import Post
from .providers import PROVIDERS, Provider, ProviderError
from .rules import Rules
from .store import Store, now_iso

log = logging.getLogger("autodelete")

# Stop scanning after this many posts in one run so huge accounts don't hang the app.
MAX_SCAN = 20000

# One run per account at a time (scheduler + "Run now" button could overlap).
_running: set[int] = set()
_running_lock = threading.Lock()


@dataclass
class RunResult:
    account_id: int
    live: bool
    scanned: int = 0
    to_delete: list[Post] = field(default_factory=list)
    kept: list[tuple[Post, str]] = field(default_factory=list)
    deleted: list[Post] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    finished: bool = False

    @property
    def summary(self) -> str:
        if self.live:
            text = f"Deleted {len(self.deleted)} of {len(self.to_delete)} matching posts ({self.scanned} scanned)"
        else:
            text = f"Preview: {len(self.to_delete)} posts would be deleted ({self.scanned} scanned)"
        if self.errors:
            text += f", {len(self.errors)} error(s)"
        return text


def build_provider(account: dict, store: Store) -> Provider:
    cls = PROVIDERS.get(account["platform"])
    if not cls:
        raise ProviderError(f"Unknown platform {account['platform']!r}")
    if cls.browser:
        from .browser import profile_dir

        return cls(account["credentials"], profile=profile_dir(store.data_dir, account["id"]),
                   archive=store.archive(account["id"]))
    return cls(account["credentials"])


def run_account(store: Store, account: dict, live: bool | None = None,
                provider: Provider | None = None, sleep=time.sleep,
                now: datetime | None = None, result: RunResult | None = None) -> RunResult:
    """Scan one account and delete (or, in preview mode, just list) posts that match its rules.

    Pass ``result`` to watch progress from another thread.
    """
    live = account["live"] if live is None else live
    result = result or RunResult(account_id=account["id"], live=live)
    result.live = live

    with _running_lock:
        if account["id"] in _running:
            result.errors.append("A run for this account is already in progress")
            return result
        _running.add(account["id"])
    try:
        _run(store, account, result, provider, sleep, now or datetime.now(timezone.utc))
    finally:
        with _running_lock:
            _running.discard(account["id"])
        store.update_account(account["id"], last_run=now_iso(), last_status=result.summary)
        result.finished = True
    return result


def _run(store: Store, account: dict, result: RunResult, provider: Provider | None, sleep, now: datetime) -> None:
    rules = Rules.from_dict(account["rules"])
    try:
        provider = provider or build_provider(account, store)
    except Exception as exc:  # noqa: BLE001
        _fail(store, account, result, exc)
        return
    try:
        _scan_and_delete(store, account, result, provider, rules, sleep, now)
    finally:
        provider.close()


def _scan_and_delete(store, account, result, provider, rules, sleep, now) -> None:
    limit = rules.max_deletes_per_run
    if provider.max_per_run:
        limit = min(limit, provider.max_per_run)
    try:
        provider.login()
        if provider.updated_credentials:
            account["credentials"].update(provider.updated_credentials)
            store.update_account(account["id"], credentials=account["credentials"])
        for post in provider.iter_posts():
            result.scanned += 1
            reason = rules.reason_to_keep(post, now)
            if reason:
                result.kept.append((post, reason))
            elif len(result.to_delete) < limit:
                result.to_delete.append(post)
            if result.scanned >= MAX_SCAN:
                break
    except Exception as exc:  # noqa: BLE001 - surface any provider failure in the UI
        _fail(store, account, result, exc)
        return

    if not result.live:
        return

    for i, post in enumerate(result.to_delete):
        if i:
            # A little randomness so browser-driven deletes don't look robotic.
            sleep(provider.delete_delay * random.uniform(0.8, 1.4))
        try:
            provider.delete(post)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{post.id}: {exc}")
            store.log(account["id"], "error", post, str(exc))
            continue
        result.deleted.append(post)
        store.log(account["id"], "deleted", post)
        store.forget_archived(account["id"], post.id)


def _fail(store: Store, account: dict, result: RunResult, exc: Exception) -> None:
    msg = str(exc) or exc.__class__.__name__
    log.warning("Account %s: %s", account["id"], msg)
    result.errors.append(msg)
    store.log(account["id"], "error", detail=msg)


def run_all(store: Store) -> list[RunResult]:
    """Run every enabled account using its own live/preview setting."""
    results = []
    for account in store.accounts():
        if account["enabled"]:
            results.append(run_account(store, account))
    return results
