"""A tiny localhost HTTP bridge so the browser extension can push orders to Actual.

The extension can't speak Actual's CRDT sync protocol from a web page, so this
optional companion exposes a minimal HTTP API on ``127.0.0.1``. It reuses the
exact same matching + write logic as the CLI (:class:`ActualSyncer`): pull
transactions from Actual, match them to the posted orders, and send per-
transaction note updates back down.

Endpoints (all JSON):

* ``GET  /health``  -> ``{"ok": true, ...}``
* ``POST /preview`` -> match + plan, **never writes** (forces dry-run)
* ``POST /sync``    -> match + write notes to Actual

Request body: ``{"orders": [...], "options": {...}}`` where ``options`` may
override ``note_mode``, ``days``, ``date_window_days``, ``tolerance_cents``,
``account``, ``payee_regex`` and ``include_positive`` for that call.

Security: binds to loopback only; an optional shared token (``--bridge-token`` /
``ASFA_BRIDGE_TOKEN``) is required via the ``X-ASFA-Token`` header when set; and
the ``Origin`` is checked against an allow-list (browser extensions by default)
to reduce DNS-rebinding / cross-site risk.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .actual_sync import ActualSyncer, SyncResult, Update
from .config import Config
from .sources.json_source import orders_from_dicts

log = logging.getLogger(__name__)

__all__ = ["process_request", "result_to_dict", "apply_options", "run_server"]

# Options a request is allowed to override (everything else comes from the
# server's launch config so the extension can't, say, point us at a new server).
_ALLOWED_OPTIONS = {
    "note_mode", "days", "date_window_days", "tolerance_cents",
    "account", "payee_regex", "include_positive", "match_shipments",
}


def apply_options(config: Config, options: Optional[Dict[str, Any]]) -> Config:
    """Return a copy of *config* with whitelisted *options* applied."""
    if not options:
        return config
    updates: Dict[str, Any] = {}
    for key, value in options.items():
        if key in _ALLOWED_OPTIONS and value is not None:
            updates[key] = value
    return dataclasses.replace(config, **updates) if updates else config


def _update_to_dict(u: Update) -> Dict[str, Any]:
    txn = u.txn
    return {
        "id": txn.id,
        "date": txn.date.isoformat() if txn.date else None,
        "amount_cents": txn.amount_cents,
        "payee": txn.payee_name,
        "action": u.action,
        "changes": u.changes,
        "memo": u.memo,
        "new_notes": u.new_notes if u.changes else None,
    }


def result_to_dict(result: SyncResult) -> Dict[str, Any]:
    """Serialise a :class:`SyncResult` into a JSON-friendly summary."""
    return {
        "ok": True,
        "committed": result.committed,
        "summary": result.summary(),
        "counts": {
            "matched": len(result.updates),
            "changed": len(result.changed),
            "unmatched_txns": len(result.unmatched_txns),
            "unmatched_orders": len(result.unmatched_orders),
        },
        "updates": [_update_to_dict(u) for u in result.updates],
        "unmatched_orders": [
            {"order_id": o.order_id,
             "date": o.order_date.isoformat() if o.order_date else None,
             "total_cents": o.total_cents}
            for o in result.unmatched_orders
        ],
    }


# Indirection so tests can monkeypatch the (actualpy-dependent) write step.
def _run_syncer(config: Config, orders) -> SyncResult:
    return ActualSyncer(config).run(orders)


def process_request(config: Config, payload: Dict[str, Any], *, write: bool) -> Dict[str, Any]:
    """Core handler: build orders, apply options, run the syncer, return a summary.

    ``write=False`` forces a dry-run (the ``/preview`` endpoint).
    """
    orders = orders_from_dicts(payload.get("orders", []))
    config = apply_options(config, payload.get("options"))
    if not write:
        config = dataclasses.replace(config, dry_run=True)
    result = _run_syncer(config, orders)
    body = result_to_dict(result)
    body["orders_received"] = len(orders)
    body["wrote"] = write and not config.dry_run
    return body


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------
DEFAULT_ALLOWED_ORIGIN_PREFIXES = (
    "chrome-extension://", "moz-extension://", "safari-web-extension://",
    "http://localhost", "http://127.0.0.1",
)


def _origin_allowed(origin: str, prefixes) -> bool:
    if not origin:
        return True  # non-browser clients (curl, tests) send no Origin
    return any(origin.startswith(p) for p in prefixes)


def _make_handler(config: Config, token: Optional[str], origin_prefixes):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        server_version = "ASFABridge/1.0"

        # Quieter logging routed through our logger.
        def log_message(self, fmt, *args):  # noqa: N802 (stdlib name)
            log.debug("%s - %s", self.address_string(), fmt % args)

        def _cors(self, origin: str) -> None:
            self.send_header("Access-Control-Allow-Origin", origin or "*")
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-ASFA-Token")
            self.send_header("Access-Control-Max-Age", "600")

        def _send(self, code: int, obj: Dict[str, Any], origin: str = "") -> None:
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._cors(origin)
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):  # noqa: N802
            origin = self.headers.get("Origin", "")
            self.send_response(204)
            self._cors(origin)
            self.end_headers()

        def do_GET(self):  # noqa: N802
            origin = self.headers.get("Origin", "")
            if self.path.rstrip("/") in ("/health", "/healthz", ""):
                self._send(200, {"ok": True, "service": "amazon-sync-for-actual",
                                 "actual_url": config.actual_url}, origin)
            else:
                self._send(404, {"ok": False, "error": "not found"}, origin)

        def do_POST(self):  # noqa: N802
            origin = self.headers.get("Origin", "")
            if not _origin_allowed(origin, origin_prefixes):
                return self._send(403, {"ok": False, "error": "origin not allowed"}, origin)
            if token and self.headers.get("X-ASFA-Token", "") != token:
                return self._send(401, {"ok": False, "error": "invalid or missing token"}, origin)

            route = self.path.rstrip("/")
            if route not in ("/sync", "/preview"):
                return self._send(404, {"ok": False, "error": "not found"}, origin)

            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError) as exc:
                return self._send(400, {"ok": False, "error": f"bad JSON: {exc}"}, origin)

            try:
                body = process_request(config, payload, write=(route == "/sync"))
            except RuntimeError as exc:  # e.g. actualpy missing / connection failure
                return self._send(502, {"ok": False, "error": str(exc)}, origin)
            except (ValueError, KeyError) as exc:
                return self._send(400, {"ok": False, "error": str(exc)}, origin)
            self._send(200, body, origin)

    return Handler


def run_server(
    config: Config,
    host: str = "127.0.0.1",
    port: int = 5007,
    token: Optional[str] = None,
    origin_prefixes: Tuple[str, ...] = DEFAULT_ALLOWED_ORIGIN_PREFIXES,
) -> None:
    """Run the bridge until interrupted. Refuses to bind to non-loopback hosts."""
    from http.server import ThreadingHTTPServer

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            f"Refusing to bind the bridge to {host!r}; loopback only "
            "(127.0.0.1/localhost) for safety."
        )

    handler = _make_handler(config, token, origin_prefixes)
    httpd = ThreadingHTTPServer((host, port), handler)
    log.info("Amazon Sync bridge listening on http://%s:%d (token=%s)",
             host, port, "set" if token else "none")
    print(f"Bridge running at http://{host}:{port}  (Ctrl-C to stop)")
    print(f"  Actual: {config.actual_url}  file={config.actual_file!r}")
    print("  POST /preview to dry-run, POST /sync to write notes.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping bridge.")
    finally:
        httpd.server_close()
