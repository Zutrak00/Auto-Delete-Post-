from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from .engine import run_all
from .store import Store, now_iso

log = logging.getLogger("autodelete")


def next_run(store: Store) -> datetime | None:
    if store.setting("schedule_enabled") != "1":
        return None
    last = store.setting("last_scheduled_run")
    hours = max(float(store.setting("interval_hours") or 24), 0.25)
    if not last:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(last) + timedelta(hours=hours)


def tick(store: Store) -> bool:
    """Run all accounts if a scheduled run is due. Returns True if it ran."""
    due = next_run(store)
    if due is None or datetime.now(timezone.utc) < due:
        return False
    store.set_setting("last_scheduled_run", now_iso())
    for result in run_all(store):
        log.info("Account %s: %s", result.account_id, result.summary)
    return True


class Scheduler(threading.Thread):
    def __init__(self, store: Store, poll_seconds: int = 60):
        super().__init__(daemon=True, name="autodelete-scheduler")
        self.store = store
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                tick(self.store)
            except Exception:  # noqa: BLE001 - keep the scheduler alive
                log.exception("Scheduled run failed")
            self._stop.wait(self.poll_seconds)

    def stop(self) -> None:
        self._stop.set()
