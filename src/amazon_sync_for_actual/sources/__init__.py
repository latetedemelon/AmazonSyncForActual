"""Amazon order ingestion sources."""

from __future__ import annotations

from .base import AmazonSource

__all__ = ["AmazonSource", "build_source"]


def build_source(config) -> AmazonSource:
    """Instantiate the configured source.

    ``csv`` is the recommended, dependency-light and fully reliable path; it
    reads the order export from Amazon's "Request My Data" download.  ``json``
    reads the browser extension's structured export.  ``selenium`` is an
    experimental best-effort scraper kept for backwards compatibility.

    As a convenience, when ``source == 'csv'`` but the path ends in ``.json`` the
    JSON reader is used, so ``--csv orders.json`` just works.
    """
    if config.source == "json" or (
        config.source == "csv" and (config.csv_path or "").lower().endswith(".json")
    ):
        from .json_source import JsonSource

        return JsonSource(config.csv_path)
    if config.source == "csv":
        from .csv_source import CsvSource

        return CsvSource(config.csv_path)
    if config.source == "selenium":
        from .selenium_source import SeleniumSource

        return SeleniumSource(
            email=config.amazon_email,
            password=config.amazon_password,
            otp_secret=config.amazon_otp_secret,
            pages=config.selenium_pages,
        )
    raise ValueError(f"Unknown source: {config.source!r}")
