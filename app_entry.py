"""Entry point for the packaged (no-Python-needed) app built with PyInstaller.

Double-clicking the app runs the dashboard and opens the browser. If something goes wrong the window stays
open so the error can be read instead of flashing and disappearing.
"""
import sys
import traceback

from autodelete.__main__ import main

if __name__ == "__main__":
    try:
        code = main(sys.argv[1:] or ["web", "--open"])
    except KeyboardInterrupt:
        code = 0
    except Exception:  # noqa: BLE001 - show any startup failure to the user
        traceback.print_exc()
        code = 1
    if code and len(sys.argv) == 1:
        input("\nSomething went wrong (details above). Press Enter to close.")
    sys.exit(code)
