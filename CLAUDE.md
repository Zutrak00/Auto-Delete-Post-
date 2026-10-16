# CLAUDE.md

## Review rule

When reviewing code or reporting on work, only flag issues that would break in production or lose data.
Reporting nothing is fine when nothing meets that bar.

## Project notes

- Python/Flask app in `autodelete/`; each social network is one file in `autodelete/providers/`.
- Run tests with `pip install -r requirements-dev.txt && pytest`.
