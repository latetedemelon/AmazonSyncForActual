import json

from amazon_sync_for_actual.diagnostics import (
    render_summary,
    summarize_file,
    summarize_text,
)

PRECOMPUTED = {
    "summary": {
        "pages": 2,
        "errors": 1,
        "health": {
            "cards": 4,
            "orders": 3,
            "orderExtractionRate": 0.75,
            "coverageRate": {"orderId": 1.0, "orderDate": 0.75,
                             "orderTotal": 0.75, "items": 1.0},
        },
        "byContext": [
            {"host": "amazon.co.uk", "pathKind": "your-orders", "pages": 1,
             "cards": 2, "orders": 1,
             "coverageRate": {"orderId": 1.0, "orderDate": 0.5,
                              "orderTotal": 0.5, "items": 1.0},
             "cardSelectors": {".order-card": 1}},
        ],
        "failurePatterns": [
            {"count": 2, "missing": ["orderTotal", "orderDate"],
             "sampleShapes": {"total": "", "date": "## Xxxxxxxx ####"},
             "signature": "orderDate+orderTotal @ [order-total-mystery]"},
        ],
        "errorCounts": [{"error": "TypeError: x is null", "count": 1}],
    }
}


def test_render_precomputed_summary():
    out = render_summary(PRECOMPUTED["summary"])
    assert "pages=2" in out
    assert "order rate 75%" in out
    assert "amazon.co.uk" in out
    assert "missing orderTotal, orderDate" in out
    assert "## Xxxxxxxx ####" in out
    assert "TypeError" in out


def test_summarize_text_with_summary():
    out = summarize_text(json.dumps(PRECOMPUTED))
    assert "extraction diagnostics" in out
    assert "coverage:" in out


def test_summarize_text_from_raw_reports():
    raw = {"reports": [
        {"kind": "page", "ordersExtracted": 2,
         "coverage": {"cards": 2, "orderId": 2, "orderDate": 2,
                      "orderTotal": 2, "items": 2}},
        {"kind": "error", "error": {"name": "TypeError", "message": "x"}},
    ]}
    out = summarize_text(json.dumps(raw))
    assert "pages=1" in out
    assert "errors=1" in out
    assert "order rate 100%" in out


def test_healthy_report_has_celebration():
    healthy = {"summary": {"pages": 1, "errors": 0,
                           "health": {"cards": 2, "orders": 2,
                                      "orderExtractionRate": 1.0,
                                      "coverageRate": {"orderId": 1.0, "orderDate": 1.0,
                                                       "orderTotal": 1.0, "items": 1.0}},
                           "byContext": [], "failurePatterns": [], "errorCounts": []}}
    assert "healthy" in render_summary(healthy["summary"])


def test_summarize_file(tmp_path):
    p = tmp_path / "diag.json"
    p.write_text(json.dumps(PRECOMPUTED), encoding="utf-8")
    out = summarize_file(str(p))
    assert "pages=2" in out
