# -*- coding: utf-8 -*-
"""Recreate the original StarTrace trend-arrow icon using only Python stdlib."""
import math
import struct
import zlib

S = 256
pixels = bytearray(S * S * 4)


def paint(x, y, color):
    if 0 <= x < S and 0 <= y < S:
        i = (y * S + x) * 4
        pixels[i:i + 4] = bytes((*color, 255))


def rounded_rect(x0, y0, x1, y1, radius, color):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            cx = min(max(x, x0 + radius), x1 - radius)
            cy = min(max(y, y0 + radius), y1 - radius)
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                paint(x, y, color)


def disk(cx, cy, radius, color):
    for y in range(max(0, cy - radius), min(S, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(S, cx + radius + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                paint(x, y, color)


def line(a, b, width, color):
    x0, y0 = a
    x1, y1 = b
    length = max(abs(x1 - x0), abs(y1 - y0))
    for step in range(length + 1):
        t = step / max(1, length)
        disk(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), width // 2, color)


def polygon(points, color):
    min_y = max(0, min(y for _, y in points))
    max_y = min(S - 1, max(y for _, y in points))
    for y in range(min_y, max_y + 1):
        xs = []
        for i, (x1, y1) in enumerate(points):
            x2, y2 = points[(i + 1) % len(points)]
            if y1 == y2 or not min(y1, y2) <= y < max(y1, y2):
                continue
            xs.append(round(x1 + (y - y1) * (x2 - x1) / (y2 - y1)))
        if len(xs) >= 2:
            for x in range(max(0, min(xs)), min(S, max(xs) + 1)):
                paint(x, y, color)


charcoal = (36, 41, 47)
white = (255, 255, 255)
blue = (47, 129, 247)
rounded_rect(8, 8, 248, 248, 48, charcoal)
rounded_rect(44, 190, 212, 202, 6, blue)
points = [(52, 158), (98, 116), (142, 137), (193, 82)]
for start, end in zip(points, points[1:]):
    line(start, end, 15, white)
for x, y in points[:-1]:
    disk(x, y, 7, white)
polygon([(193, 59), (188, 90), (218, 84)], white)


def png_bytes():
    raw = b"".join(b"\0" + pixels[y * S * 4:(y + 1) * S * 4] for y in range(S))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


png = png_bytes()
with open("app.png", "wb") as f:
    f.write(png)

# A 32-bit Windows icon image (BGRA XOR bitmap + 1-bit AND transparency mask).
bgra = bytearray()
for y in range(S - 1, -1, -1):
    for x in range(S):
        i = (y * S + x) * 4
        r, g, b, a = pixels[i:i + 4]
        bgra.extend((b, g, r, a))
mask = b"\0" * (((S + 31) // 32) * 4 * S)
dib = struct.pack("<IIIHHIIIIII", 40, S, S * 2, 1, 32, 0, len(bgra) + len(mask), 0, 0, 0, 0) + bgra + mask
entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(dib), 22)
with open("app.ico", "wb") as f:
    f.write(struct.pack("<HHH", 0, 1, 1) + entry + dib)
