import socket

import pytest

from autodelete import __main__ as cli


@pytest.fixture
def no_server(monkeypatch):
    started = {}
    monkeypatch.setattr("flask.Flask.run", lambda self, **kw: started.update(kw))
    monkeypatch.setattr("autodelete.web.Scheduler.start", lambda self: None)
    return started


def test_picks_next_free_port(tmp_path, monkeypatch, no_server):
    monkeypatch.setattr(cli, "DEFAULT_PORT", _free_base())
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", cli.DEFAULT_PORT))
        assert cli.main(["--db", str(tmp_path / "db"), "web"]) == 0
    assert no_server["port"] == cli.DEFAULT_PORT + 1


def test_second_launch_reuses_running_copy(tmp_path, monkeypatch, no_server):
    base = _free_base()
    monkeypatch.setattr(cli, "DEFAULT_PORT", base)
    monkeypatch.setattr(cli, "_already_running", lambda port: port == base + 1)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", base))
        assert cli.main(["--db", str(tmp_path / "db"), "web", "--open"]) == 0
    assert no_server == {}  # did not start a second server


def _free_base() -> int:
    """Find 10 consecutive free ports to use as the default range in tests."""
    for base in range(20000, 60000, 10):
        if all(cli._port_free("127.0.0.1", p) for p in range(base, base + 10)):
            return base
    raise RuntimeError("no free port range")
