"""Layered configuration.

Settings are resolved with the precedence **CLI args > environment variables >
INI file > built-in defaults**.  Environment variables are prefixed ``ASFA_``.
For convenience the loader also understands the original project's flat
``[DEFAULT]`` ``credentials.ini`` keys (``actualBaseUrl``, ``otpSecret`` ...).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .dates import parse_date
from .matching import DEFAULT_PAYEE_REGEX
from .memo import MemoOptions

__all__ = ["Config", "load_config"]

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise ValueError(f"Cannot interpret {value!r} as a boolean")


def _as_cert(value: Any):
    """``cert`` is either a boolean (verify / don't verify) or a path to a CA bundle."""
    if isinstance(value, bool):
        return value
    s = str(value).strip()
    if s.lower() in _TRUE:
        return True
    if s.lower() in _FALSE:
        return False
    return s  # treat as a path


@dataclass
class Config:
    # --- Actual connection -------------------------------------------------
    actual_url: str = "http://localhost:5006"
    actual_password: Optional[str] = None
    actual_token: Optional[str] = None
    actual_file: Optional[str] = None
    actual_encryption_password: Optional[str] = None
    actual_cert: Any = True
    account: Optional[str] = None

    # --- Amazon source -----------------------------------------------------
    source: str = "csv"  # "csv" | "selenium"
    csv_path: Optional[str] = None
    amazon_email: Optional[str] = None
    amazon_password: Optional[str] = None
    amazon_otp_secret: Optional[str] = None
    selenium_pages: int = 3

    # --- Matching ----------------------------------------------------------
    days: int = 90
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    date_window_days: int = 5
    tolerance_cents: int = 0
    payee_regex: str = DEFAULT_PAYEE_REGEX
    match_shipments: bool = True
    include_positive: bool = False

    # --- Splitting ---------------------------------------------------------
    # "off"   -> never split; just write notes (default, backwards compatible)
    # "items" -> split a matched transaction into one child per item, but ONLY
    #            when item amounts reconcile exactly; otherwise fall back to notes
    split_mode: str = "off"

    # --- Memo rendering ----------------------------------------------------
    note_mode: str = "fill"  # "fill" | "prepend" | "append" | "overwrite"
    max_words_per_item: int = 8
    max_items: int = 0
    separator: str = " | "
    include_quantity: bool = True
    note_prefix: str = ""
    max_length: int = 0

    # --- Bridge (local HTTP companion for the browser extension) -----------
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 5007
    bridge_token: Optional[str] = None

    # --- Behaviour ---------------------------------------------------------
    dry_run: bool = False
    verbose: bool = False

    def date_range(self) -> "Tuple[date, date]":
        """Resolve the (start, end) window to query transactions for."""
        end = self.end_date or date.today()
        start = self.start_date or (end - timedelta(days=self.days))
        return start, end

    def memo_options(self) -> MemoOptions:
        return MemoOptions(
            max_words_per_item=self.max_words_per_item,
            max_items=self.max_items,
            separator=self.separator,
            include_quantity=self.include_quantity,
            prefix=self.note_prefix,
            max_length=self.max_length,
        )

    def validate(self) -> List[str]:
        """Return a list of human-readable configuration problems (empty == OK)."""
        problems: List[str] = []
        if self.source not in ("csv", "json", "selenium"):
            problems.append(
                f"Unknown source {self.source!r} (expected 'csv', 'json' or 'selenium')."
            )
        if self.note_mode not in ("fill", "prepend", "append", "overwrite"):
            problems.append(
                f"Unknown note_mode {self.note_mode!r} "
                "(expected fill/prepend/append/overwrite)."
            )
        if self.split_mode not in ("off", "items"):
            problems.append(
                f"Unknown split_mode {self.split_mode!r} (expected off/items)."
            )
        if self.source in ("csv", "json") and not self.csv_path:
            problems.append(f"source={self.source} requires --csv / csv_path to be set.")
        if self.source == "selenium" and not (self.amazon_email and self.amazon_password):
            problems.append("source=selenium requires amazon_email and amazon_password.")
        return problems


# Maps a Config attribute to its coercion function plus where to find it in an
# INI file ([section] key) and as an environment variable.
_FieldSpec = Tuple[str, Any, str, str, str]
_SPECS: List[_FieldSpec] = [
    ("actual_url", str, "actual", "url", "ASFA_ACTUAL_URL"),
    ("actual_password", str, "actual", "password", "ASFA_ACTUAL_PASSWORD"),
    ("actual_token", str, "actual", "token", "ASFA_ACTUAL_TOKEN"),
    ("actual_file", str, "actual", "file", "ASFA_ACTUAL_FILE"),
    ("actual_encryption_password", str, "actual", "encryption_password", "ASFA_ACTUAL_ENCRYPTION_PASSWORD"),
    ("actual_cert", _as_cert, "actual", "cert", "ASFA_ACTUAL_CERT"),
    ("account", str, "actual", "account", "ASFA_ACCOUNT"),
    ("source", str, "amazon", "source", "ASFA_SOURCE"),
    ("csv_path", str, "amazon", "csv_path", "ASFA_CSV_PATH"),
    ("amazon_email", str, "amazon", "email", "ASFA_AMAZON_EMAIL"),
    ("amazon_password", str, "amazon", "password", "ASFA_AMAZON_PASSWORD"),
    ("amazon_otp_secret", str, "amazon", "otp_secret", "ASFA_AMAZON_OTP_SECRET"),
    ("selenium_pages", int, "amazon", "pages", "ASFA_SELENIUM_PAGES"),
    ("days", int, "matching", "days", "ASFA_DAYS"),
    ("date_window_days", int, "matching", "date_window_days", "ASFA_DATE_WINDOW_DAYS"),
    ("tolerance_cents", int, "matching", "tolerance_cents", "ASFA_TOLERANCE_CENTS"),
    ("payee_regex", str, "matching", "payee_regex", "ASFA_PAYEE_REGEX"),
    ("match_shipments", _as_bool, "matching", "match_shipments", "ASFA_MATCH_SHIPMENTS"),
    ("include_positive", _as_bool, "matching", "include_positive", "ASFA_INCLUDE_POSITIVE"),
    ("split_mode", str, "memo", "split_mode", "ASFA_SPLIT_MODE"),
    ("note_mode", str, "memo", "mode", "ASFA_NOTE_MODE"),
    ("max_words_per_item", int, "memo", "max_words_per_item", "ASFA_MAX_WORDS_PER_ITEM"),
    ("max_items", int, "memo", "max_items", "ASFA_MAX_ITEMS"),
    ("separator", str, "memo", "separator", "ASFA_SEPARATOR"),
    ("include_quantity", _as_bool, "memo", "include_quantity", "ASFA_INCLUDE_QUANTITY"),
    ("note_prefix", str, "memo", "prefix", "ASFA_NOTE_PREFIX"),
    ("max_length", int, "memo", "max_length", "ASFA_MAX_LENGTH"),
    ("bridge_host", str, "bridge", "host", "ASFA_BRIDGE_HOST"),
    ("bridge_port", int, "bridge", "port", "ASFA_BRIDGE_PORT"),
    ("bridge_token", str, "bridge", "token", "ASFA_BRIDGE_TOKEN"),
    ("dry_run", _as_bool, "behaviour", "dry_run", "ASFA_DRY_RUN"),
    ("verbose", _as_bool, "behaviour", "verbose", "ASFA_VERBOSE"),
]

# Legacy flat keys from the original credentials.ini ([DEFAULT] section).
_LEGACY_DEFAULT: Dict[str, str] = {
    "actualbaseurl": "actual_url",
    "actualtoken": "actual_token",
    "actualpassword": "actual_password",
    "useremail": "amazon_email",
    "userpassword": "amazon_password",
    "otpsecret": "amazon_otp_secret",
}

_DATE_FIELDS = {"start_date", "end_date"}


def _read_ini(path: str) -> Dict[str, str]:
    """Flatten an INI file into a ``{config_attr: raw_string}`` dict."""
    import configparser

    parser = configparser.ConfigParser()
    # Preserve case of keys; default optionxform lowercases which is fine here.
    parser.read(path)
    values: Dict[str, str] = {}

    # Section-based, modern layout.
    for attr, _coerce, section, key, _env in _SPECS:
        if parser.has_option(section, key):
            values[attr] = parser.get(section, key)
    for field_name in _DATE_FIELDS:
        if parser.has_option("matching", field_name):
            values[field_name] = parser.get("matching", field_name)

    # Legacy flat [DEFAULT] keys (don't clobber anything already set above).
    for legacy_key, attr in _LEGACY_DEFAULT.items():
        if parser.has_option("DEFAULT", legacy_key) and attr not in values:
            values[attr] = parser.get("DEFAULT", legacy_key)

    return values


def _read_env() -> Dict[str, str]:
    values: Dict[str, str] = {}
    for attr, _coerce, _section, _key, env in _SPECS:
        if env in os.environ and os.environ[env] != "":
            values[attr] = os.environ[env]
    for field_name in _DATE_FIELDS:
        env = f"ASFA_{field_name.upper()}"
        if env in os.environ and os.environ[env] != "":
            values[field_name] = os.environ[env]
    return values


def _coerce_value(attr: str, value: Any) -> Any:
    if attr in _DATE_FIELDS:
        if value is None or isinstance(value, date):
            return value
        parsed = parse_date(value)
        if parsed is None:
            raise ValueError(f"Could not parse date for {attr}: {value!r}")
        return parsed
    for spec_attr, coerce, _section, _key, _env in _SPECS:
        if spec_attr == attr:
            return coerce(value)
    return value


def load_config(path: Optional[str] = None, overrides: Optional[Dict[str, Any]] = None) -> Config:
    """Build a :class:`Config` from an optional INI file, env vars and CLI overrides.

    *overrides* (typically parsed CLI args) win over everything; only non-``None``
    values are applied so "flag not given" falls through to the next layer.
    """
    merged: Dict[str, Any] = {}

    if path and os.path.exists(path):
        merged.update(_read_ini(path))
    merged.update(_read_env())
    if overrides:
        merged.update({k: v for k, v in overrides.items() if v is not None})

    valid_attrs = {f.name for f in fields(Config)}
    kwargs: Dict[str, Any] = {}
    for attr, raw in merged.items():
        if attr not in valid_attrs:
            continue
        kwargs[attr] = _coerce_value(attr, raw)

    return Config(**kwargs)
