from __future__ import annotations

import argparse
import logging
import os
import sys

from .engine import run_account
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autodelete", description="Automatically delete your old social media posts.")
    parser.add_argument("--db", help="Path to the database (default: ./data/autodelete.db or $AUTODELETE_DB)")
    sub = parser.add_subparsers(dest="command", required=True)

    web = sub.add_parser("web", help="Start the web dashboard (default http://127.0.0.1:8080)")
    web.add_argument("--host", default="127.0.0.1",
                     help="Use 0.0.0.0 only behind a password (AUTODELETE_PASSWORD) and HTTPS")
    web.add_argument("--port", type=int, default=8080)
    web.add_argument("--open", action="store_true", help="Open the dashboard in your browser")

    run = sub.add_parser("run", help="Run every enabled account once (for cron / Task Scheduler)")
    run.add_argument("--preview", action="store_true", help="Never delete, even for Live accounts")
    run.add_argument("--account", type=int, help="Only this account ID")

    sub.add_parser("list", help="List connected accounts")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store(args.db)

    if args.command == "web":
        from .web import create_app

        if args.host not in ("127.0.0.1", "localhost") and not os.environ.get("AUTODELETE_PASSWORD"):
            print("Refusing to listen on a public address without AUTODELETE_PASSWORD set.", file=sys.stderr)
            return 2
        app = create_app(store)
        url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
        print(f"Open {url} in your browser. Press Ctrl+C to stop.")
        if args.open:
            import threading
            import webbrowser

            threading.Timer(1.0, webbrowser.open, args=(url,)).start()
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
        return 0

    if args.command == "list":
        for acc in store.accounts():
            mode = "LIVE" if acc["live"] else "preview"
            sched = "scheduled" if acc["enabled"] else "manual"
            print(f"{acc['id']:>3}  {acc['platform']:<9} {acc['label']:<25} {mode:<8} {sched:<9} {acc['last_status'] or ''}")
        return 0

    exit_code = 0
    for acc in store.accounts():
        if args.account is not None and acc["id"] != args.account:
            continue
        if args.account is None and not acc["enabled"]:
            continue
        result = run_account(store, acc, live=False if args.preview else None)
        print(f"[{acc['label']}] {result.summary}")
        for err in result.errors:
            print(f"  error: {err}")
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
