"""Summarize a diagnostics report exported by the browser extension.

The extension writes a redacted JSON report (``asfa-diagnostics-*.json``) that
contains a precomputed ``summary`` plus the raw redacted ``reports``. This module
renders that into a short, human-readable verdict so extraction problems are easy
to triage, e.g.::

    amazon-sync-for-actual --diag-report asfa-diagnostics-2024-01-31.json

It is pure (stdlib only) and never sees personal data -- the report is already
redacted to coverage rates, CSS class hints and value *shapes*.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

__all__ = ["summarize_text", "summarize_file", "render_summary"]


def _pct(rate) -> str:
    return "n/a" if rate is None else f"{round(rate * 100)}%"


def render_summary(summary: Dict[str, Any]) -> str:
    """Render a precomputed ``summary`` dict into a text report."""
    lines: List[str] = []
    health = summary.get("health", {})
    cov = health.get("coverageRate", {})
    lines.append("Amazon Sync for Actual — extraction diagnostics")
    lines.append("=" * 48)
    lines.append(
        f"pages={summary.get('pages', 0)} errors={summary.get('errors', 0)} "
        f"cards={health.get('cards', 0)} orders={health.get('orders', 0)} "
        f"(order rate {_pct(health.get('orderExtractionRate'))})"
    )
    lines.append(
        "coverage: "
        f"orderId {_pct(cov.get('orderId'))}, "
        f"date {_pct(cov.get('orderDate'))}, "
        f"total {_pct(cov.get('orderTotal'))}, "
        f"items {_pct(cov.get('items'))}"
    )

    by_ctx = summary.get("byContext", [])
    if by_ctx:
        lines.append("")
        lines.append("By marketplace / page:")
        for c in by_ctx:
            cc = c.get("coverageRate", {})
            selectors = ", ".join((c.get("cardSelectors") or {}).keys()) or "(none matched)"
            lines.append(
                f"  {c.get('host', '?')} [{c.get('pathKind', '?')}] "
                f"pages={c.get('pages', 0)} cards={c.get('cards', 0)} "
                f"orders={c.get('orders', 0)}"
            )
            lines.append(
                f"      coverage: id {_pct(cc.get('orderId'))}, date {_pct(cc.get('orderDate'))}, "
                f"total {_pct(cc.get('orderTotal'))}, items {_pct(cc.get('items'))}"
            )
            lines.append(f"      card selector: {selectors}")

    failures = summary.get("failurePatterns", [])
    if failures:
        lines.append("")
        lines.append("Top failure patterns (most actionable first):")
        for f in failures:
            lines.append(f"  x{f.get('count', 0)}  missing {', '.join(f.get('missing', []))}")
            shapes = f.get("sampleShapes", {})
            if shapes.get("total") or shapes.get("date"):
                lines.append(
                    f"        shapes: total={shapes.get('total','') or '—'} "
                    f"date={shapes.get('date','') or '—'}"
                )
            lines.append(f"        signature: {f.get('signature', '')}")

    errors = summary.get("errorCounts", [])
    if errors:
        lines.append("")
        lines.append("Errors:")
        for e in errors:
            lines.append(f"  x{e.get('count', 0)}  {e.get('error', '')}")

    if not failures and not errors and health.get("cards"):
        lines.append("")
        lines.append("No failures recorded — extraction looks healthy. 🎉")
    return "\n".join(lines)


def summarize_text(text: str) -> str:
    """Summarize the JSON content of a diagnostics export."""
    data = json.loads(text)
    summary = data.get("summary") if isinstance(data, dict) else None
    if summary is None:
        # Accept a bare list of reports or a {"reports": [...]} object by
        # recomputing a minimal summary client-side.
        reports = data.get("reports") if isinstance(data, dict) else data
        summary = _summarize_reports(reports or [])
    return render_summary(summary)


def summarize_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return summarize_text(handle.read())


def _rate(num: int, den: int):
    return round(num / den, 3) if den else None


def _summarize_reports(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A minimal Python port of the JS summarizer, for raw report lists."""
    pages = errors = 0
    totals = {"cards": 0, "orders": 0, "orderId": 0, "orderDate": 0, "orderTotal": 0, "items": 0}
    for r in reports:
        if not isinstance(r, dict):
            continue
        if r.get("kind") == "error":
            errors += 1
            continue
        pages += 1
        cov = r.get("coverage", {})
        totals["cards"] += cov.get("cards", 0)
        totals["orders"] += r.get("ordersExtracted", 0)
        for k in ("orderId", "orderDate", "orderTotal", "items"):
            totals[k] += cov.get(k, 0)
    return {
        "pages": pages,
        "errors": errors,
        "health": {
            "cards": totals["cards"],
            "orders": totals["orders"],
            "orderExtractionRate": _rate(totals["orders"], totals["cards"]),
            "coverageRate": {
                "orderId": _rate(totals["orderId"], totals["cards"]),
                "orderDate": _rate(totals["orderDate"], totals["cards"]),
                "orderTotal": _rate(totals["orderTotal"], totals["cards"]),
                "items": _rate(totals["items"], totals["cards"]),
            },
        },
        "byContext": [],
        "failurePatterns": [],
        "errorCounts": [],
    }
