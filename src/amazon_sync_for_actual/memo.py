"""Turn a list of items into the note string written onto a transaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from .models import AmazonItem

__all__ = ["MemoOptions", "build_memo", "format_item"]


@dataclass
class MemoOptions:
    """Knobs controlling how the transaction note is rendered."""

    max_words_per_item: int = 8
    max_items: int = 0          # 0 == unlimited
    separator: str = " | "
    include_quantity: bool = True
    prefix: str = ""
    max_length: int = 0         # 0 == unlimited
    ellipsis: str = "…"


def _truncate_words(name: str, max_words: int) -> str:
    words = name.split()
    if max_words and len(words) > max_words:
        return " ".join(words[:max_words])
    return " ".join(words)


def format_item(item: AmazonItem, opts: Optional[MemoOptions] = None) -> str:
    """Render a single item as it will appear in the note."""
    opts = opts or MemoOptions()
    name = _truncate_words(item.name, opts.max_words_per_item)
    if opts.include_quantity and item.quantity and item.quantity > 1:
        return f"{item.quantity}x {name}"
    return name


def build_memo(items: Iterable[AmazonItem], opts: Optional[MemoOptions] = None) -> str:
    """Build the full note string for *items*.

    Returns an empty string when there is nothing meaningful to write (so the
    caller can decide to skip the transaction entirely).
    """
    opts = opts or MemoOptions()
    items = [item for item in items if item and item.name and item.name.strip()]
    if not items:
        return ""

    if opts.max_items and len(items) > opts.max_items:
        parts: List[str] = [format_item(item, opts) for item in items[: opts.max_items]]
        parts.append(f"+{len(items) - opts.max_items} more")
    else:
        parts = [format_item(item, opts) for item in items]

    memo = opts.prefix + opts.separator.join(parts)

    if opts.max_length and len(memo) > opts.max_length:
        keep = max(0, opts.max_length - len(opts.ellipsis))
        memo = memo[:keep].rstrip() + opts.ellipsis
    return memo
