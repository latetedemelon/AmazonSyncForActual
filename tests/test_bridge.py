"""Tests for the local extension bridge.

The actualpy-dependent write step (`bridge._run_syncer`) is monkeypatched, so
these run fully offline while still exercising request parsing, option handling,
the HTTP routing, CORS, token auth and JSON responses.
"""

import json
import threading
from datetime import date
from http.client import HTTPConnection

import pytest

from amazon_sync_for_actual import bridge
from amazon_sync_for_actual.actual_sync import SyncResult, Update
from amazon_sync_for_actual.config import Config
from amazon_sync_for_actual.matching import TxnView


def _fake_result(committed=True):
    txn = TxnView(id="t1", amount_cents=-4376, date=date(2024, 1, 11),
                  payee_name="Amazon.com", notes="")
    upd = Update(txn=txn, memo="Trash Bags", new_notes="Trash Bags", action="write")
    return SyncResult(updates=[upd], unmatched_txns=[], unmatched_orders=[],
                      committed=committed)


def test_apply_options_whitelist():
    cfg = Config(note_mode="fill", days=90, actual_url="http://keep")
    out = bridge.apply_options(cfg, {"note_mode": "append", "days": 30,
                                     "actual_url": "http://evil"})
    assert out.note_mode == "append"
    assert out.days == 30
    assert out.actual_url == "http://keep"  # not overridable


def test_result_to_dict_shape():
    body = bridge.result_to_dict(_fake_result())
    assert body["ok"] is True
    assert body["counts"]["changed"] == 1
    assert body["updates"][0]["action"] == "write"
    assert body["updates"][0]["new_notes"] == "Trash Bags"


def test_process_request_preview_forces_dry_run(monkeypatch):
    seen = {}

    def fake_run(config, orders):
        seen["dry_run"] = config.dry_run
        seen["orders"] = len(orders)
        return _fake_result(committed=False)

    monkeypatch.setattr(bridge, "_run_syncer", fake_run)
    payload = {"orders": [{"orderId": "A", "orderTotalCents": 4376,
                           "items": [{"name": "Trash Bags"}]}]}
    body = bridge.process_request(Config(), payload, write=False)
    assert seen["dry_run"] is True          # preview never writes
    assert seen["orders"] == 1
    assert body["orders_received"] == 1
    assert body["wrote"] is False


# ---- HTTP layer ----------------------------------------------------------

@pytest.fixture()
def server(monkeypatch):
    from http.server import ThreadingHTTPServer

    monkeypatch.setattr(bridge, "_run_syncer", lambda c, o: _fake_result())
    handler = bridge._make_handler(
        Config(actual_url="http://localhost:5006"),
        token="secret",
        origin_prefixes=bridge.DEFAULT_ALLOWED_ORIGIN_PREFIXES,
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port
    httpd.shutdown()
    httpd.server_close()


def _post(port, path, body, headers=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, json.dumps(body),
                 headers or {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, data


def test_health(server):
    conn = HTTPConnection("127.0.0.1", server, timeout=5)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 200
    assert body["ok"] is True


def test_sync_requires_token(server):
    status, body = _post(server, "/sync", {"orders": []})
    assert status == 401
    assert body["ok"] is False


def test_sync_with_token_ok(server):
    status, body = _post(
        server, "/sync", {"orders": [{"orderId": "A", "orderTotalCents": 4376,
                                       "items": [{"name": "Trash Bags"}]}]},
        headers={"Content-Type": "application/json", "X-ASFA-Token": "secret"},
    )
    assert status == 200
    assert body["committed"] is True
    assert body["counts"]["changed"] == 1


def test_bad_json(server):
    conn = HTTPConnection("127.0.0.1", server, timeout=5)
    conn.request("POST", "/sync", "{not json",
                 {"Content-Type": "application/json", "X-ASFA-Token": "secret"})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 400


def test_forbidden_origin(server):
    status, body = _post(
        server, "/preview", {"orders": []},
        headers={"Content-Type": "application/json", "X-ASFA-Token": "secret",
                 "Origin": "https://evil.example"},
    )
    assert status == 403


def test_unknown_route(server):
    status, body = _post(
        server, "/nope", {},
        headers={"Content-Type": "application/json", "X-ASFA-Token": "secret"},
    )
    assert status == 404


def test_run_server_refuses_non_loopback(monkeypatch):
    monkeypatch.delenv("ASFA_BRIDGE_ALLOW_REMOTE", raising=False)
    with pytest.raises(ValueError):
        bridge.run_server(Config(), host="0.0.0.0")


def test_run_server_allows_non_loopback_with_env(monkeypatch):
    """ASFA_BRIDGE_ALLOW_REMOTE=1 opts in to a non-loopback bind (e.g. 0.0.0.0 in a container)."""
    import http.server

    monkeypatch.setenv("ASFA_BRIDGE_ALLOW_REMOTE", "1")
    bound = {}

    class _FakeServer:
        def __init__(self, addr, handler):
            bound["addr"] = addr

        def serve_forever(self):
            raise KeyboardInterrupt  # return immediately, as if Ctrl-C

        def server_close(self):
            bound["closed"] = True

    monkeypatch.setattr(http.server, "ThreadingHTTPServer", _FakeServer)
    bridge.run_server(Config(actual_url="http://x"), host="0.0.0.0", port=5007)
    assert bound["addr"] == ("0.0.0.0", 5007)


def test_run_server_env_must_be_truthy(monkeypatch):
    """A falsy ASFA_BRIDGE_ALLOW_REMOTE value still refuses a non-loopback bind."""
    monkeypatch.setenv("ASFA_BRIDGE_ALLOW_REMOTE", "0")
    with pytest.raises(ValueError):
        bridge.run_server(Config(), host="0.0.0.0")


def test_run_server_port_in_use_gives_actionable_error():
    import socket
    from amazon_sync_for_actual import bridge as br
    # Occupy a loopback port, then ask the bridge to bind the same one.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    taken = s.getsockname()[1]
    try:
        with pytest.raises(RuntimeError) as exc:
            br.run_server(Config(), host="127.0.0.1", port=taken)
        msg = str(exc.value)
        assert "--port" in msg and str(taken) in msg
    finally:
        s.close()
