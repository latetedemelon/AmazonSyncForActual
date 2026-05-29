#!/usr/bin/env python3
"""Generate the extension's PNG icons with the standard library only.

Draws a simple "itemized receipt" glyph (white card + teal lines) on an
Amazon-blue rounded square. Run from this directory:  python3 make_icons.py
"""
from __future__ import annotations

import struct
import zlib

BLUE = (20, 110, 180, 255)     # Amazon blue background
CARD = (255, 255, 255, 255)    # white receipt
LINE = (20, 110, 180, 255)     # receipt lines (match bg)
CLEAR = (0, 0, 0, 0)


def _rounded(x, y, w, h, r):
    """Return True if (x, y) is inside the rounded-rect [0,w)x[0,h) with radius r."""
    if r <= 0:
        return True
    if x >= r and x < w - r:
        return True
    if y >= r and y < h - r:
        return True
    cx = r - 1 if x < r else w - r
    cy = r - 1 if y < r else h - r
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size):
    px = [[CLEAR for _ in range(size)] for _ in range(size)]
    radius = max(2, size // 6)
    for y in range(size):
        for x in range(size):
            if _rounded(x, y, size, size, radius):
                px[y][x] = BLUE

    # White receipt card occupying the centre.
    m = max(2, round(size * 0.22))
    cw0, cw1 = m, size - m
    ch0, ch1 = max(2, round(size * 0.16)), size - max(2, round(size * 0.16))
    for y in range(ch0, ch1):
        for x in range(cw0, cw1):
            px[y][x] = CARD

    # Horizontal "item" lines on the receipt.
    line_h = max(1, size // 16)
    gap = max(1, size // 8)
    lx0, lx1 = cw0 + max(1, size // 12), cw1 - max(1, size // 12)
    yy = ch0 + gap
    while yy + line_h <= ch1 - gap // 2:
        width = lx1 - lx0
        end = lx1 if (yy // gap) % 2 == 0 else lx0 + int(width * 0.6)
        for y in range(yy, yy + line_h):
            for x in range(lx0, end):
                px[y][x] = LINE
        yy += gap

    return px


def write_png(path, px):
    size = len(px)
    raw = bytearray()
    for row in px:
        raw.append(0)  # filter type 0
        for (r, g, b, a) in row:
            raw += bytes((r, g, b, a))

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


if __name__ == "__main__":
    for s in (16, 48, 128):
        write_png(f"icon{s}.png", render(s))
        print(f"wrote icon{s}.png")
