from __future__ import annotations

import logging
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

    @property
    def summary(self) -> str:
        if self.live:
            text = f"Deleted {len(self.deleted)} of {len(self.to_delete)} matching posts ({self.scanned} scanned)"
        else:
            text = f"Preview: {len(self.to_delete)} posts would be deleted ({self.scanned} scanned)"
        if self.errors:
            text += f", {len(self.errors)} error(s)"
        return text


def build_provider(account: dict) -> Provider:
    cls = PROVIDERS.get(account["platform"])
    if not cls:
        raise ProviderError(f"Unknown platform {account['platform']!r}")
    return cls(account["credentials"])


def run_account(store: Store, account: dict, live: bool | None = None,
                provider: Provider | None = None, sleep=time.sleep,
                now: datetime | None = None) -> RunResult:
    """Scan one account and delete (or, in preview mode, just list) posts that match its rules."""
    live = account["live"] if live is None else live
    result = RunResult(account_id=account["id"], live=live)

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
    return result


def _run(store: Store, account: dict, result: RunResult, provider: Provider | None, sleep, now: datetime) -> None:
    rules = Rules.from_dict(account["rules"])
    try:
        provider = provider or build_provider(account)
        provider.login()
        if provider.updated_credentials:
            account["credentials"].update(provider.updated_credentials)
            store.update_account(account["id"], credentials=account["credentials"])
        for post in provider.iter_posts():
            result.scanned += 1
            reason = rules.reason_to_keep(post, now)
            if reason:
                result.kept.append((post, reason))
            elif len(result.to_delete) < rules.max_deletes_per_run:
                result.to_delete.append(post)
            if result.scanned >= MAX_SCAN:
                break
    except Exception as exc:  # noqa: BLE001 - surface any provider failure in the UI
        msg = str(exc) or exc.__class__.__name__
        log.warning("Account %s: %s", account["id"], msg)
        result.errors.append(msg)
        store.log(account["id"], "error", detail=msg)
        return

    if not result.live:
        return

    for i, post in enumerate(result.to_delete):
        if i:
            sleep(provider.delete_delay)
        try:
            provider.delete(post)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{post.id}: {exc}")
            store.log(account["id"], "error", post, str(exc))
            continue
        result.deleted.append(post)
        store.log(account["id"], "deleted", post)


def run_all(store: Store) -> list[RunResult]:
    """Run every enabled account using its own live/preview setting."""
    results = []
    for account in store.accounts():
        if account["enabled"]:
            results.append(run_account(store, account))
    return results
