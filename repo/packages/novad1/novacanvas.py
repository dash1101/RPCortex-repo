# Desc: Nova D1 UI canvas — 1-bit MONO_VLSB framebuffer + drawing primitives.
# File: /Packages/NovaD1/novacanvas.py
#
# Pure Python (runs identically on MicroPython AND CPython, so the PC mock render
# is pixel-true to the panel). The buffer layout is MONO_VLSB — exactly what the
# SH1106/SSD1306 page memory expects — so a driver just streams `buf` out.
#   byte index = (y >> 3) * width + x   ;   bit = 1 << (y & 7)   (a column of 8px)
#
# Text uses the shared 6x8 font in novafont (NOT framebuf), so device == mock.
# char()/text() take an optional scale (scale=2 doubles each pixel for big text).
# MicroPython-safe: no f-strings, positional split, .format() only.

import novafont as _f


class Canvas:
    def __init__(self, w=128, h=64):
        self.w = w
        self.h = h
        self.pages = h // 8
        self.buf = bytearray(w * self.pages)

    def clear(self, c=0):
        v = 0xff if c else 0x00
        for i in range(len(self.buf)):
            self.buf[i] = v

    def pixel(self, x, y, c=1):
        if x < 0 or x >= self.w or y < 0 or y >= self.h:
            return
        idx = (y >> 3) * self.w + x
        bit = 1 << (y & 7)
        if c:
            self.buf[idx] |= bit
        else:
            self.buf[idx] &= (~bit) & 0xff

    def hline(self, x, y, n, c=1):
        for i in range(n):
            self.pixel(x + i, y, c)

    def vline(self, x, y, n, c=1):
        for i in range(n):
            self.pixel(x, y + i, c)

    def line(self, x0, y0, x1, y1, c=1):
        dx = abs(x1 - x0); dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.pixel(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy

    def rect(self, x, y, w, h, c=1):
        self.hline(x, y, w, c); self.hline(x, y + h - 1, w, c)
        self.vline(x, y, h, c); self.vline(x + w - 1, y, h, c)

    def fill_rect(self, x, y, w, h, c=1):
        # Byte-level fill (per page band), not per-pixel — ~8x fewer ops, which
        # keeps full-screen UI redraws fast enough to animate smoothly.
        if w <= 0 or h <= 0:
            return
        x0 = 0 if x < 0 else x
        x1 = self.w if x + w > self.w else x + w
        y0 = 0 if y < 0 else y
        y1 = self.h if y + h > self.h else y + h
        if x0 >= x1 or y0 >= y1:
            return
        buf = self.buf
        W = self.w
        yy = y0
        while yy < y1:
            page = yy >> 3
            ptop = page << 3
            rtop = yy - ptop
            rbot = (y1 if y1 < ptop + 8 else ptop + 8) - ptop
            mask = 0
            for r in range(rtop, rbot):
                mask |= (1 << r)
            base = page * W
            if c:
                for xx in range(x0, x1):
                    buf[base + xx] |= mask
            else:
                inv = (~mask) & 0xff
                for xx in range(x0, x1):
                    buf[base + xx] &= inv
            yy = ptop + 8

    def circle(self, cx, cy, r, c=1):
        x = r; y = 0; err = 1 - r
        while x >= y:
            self.pixel(cx + x, cy + y, c); self.pixel(cx + y, cy + x, c)
            self.pixel(cx - x, cy + y, c); self.pixel(cx - y, cy + x, c)
            self.pixel(cx - x, cy - y, c); self.pixel(cx - y, cy - x, c)
            self.pixel(cx + x, cy - y, c); self.pixel(cx + y, cy - x, c)
            y += 1
            if err < 0:
                err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def fill_circle(self, cx, cy, r, c=1):
        for dy in range(-r, r + 1):
            dx = int((r * r - dy * dy) ** 0.5)
            self.hline(cx - dx, cy + dy, 2 * dx + 1, c)

    def char(self, x, y, code, c=1, scale=1):
        if code < _f.FIRST or code > _f.FIRST + 0x5e:
            code = ord('?')
        gi = (code - _f.FIRST) * _f.WIDTH
        for col in range(_f.WIDTH):
            bits = _f.DATA[gi + col]
            for row in range(_f.HEIGHT):
                if bits & (1 << row):
                    if scale == 1:
                        self.pixel(x + col, y + row, c)
                    else:
                        self.fill_rect(x + col * scale, y + row * scale, scale, scale, c)

    def text(self, x, y, s, c=1, scale=1):
        cx = x
        for ch in s:
            self.char(cx, y, ord(ch), c, scale)
            cx += _f.ADVANCE * scale

    def text_width(self, s, scale=1):
        return len(s) * _f.ADVANCE * scale

    def icon(self, x, y, rows, c=1):
        # rows = iterable of bytes; each byte is one row, MSB = leftmost column.
        for r in range(len(rows)):
            b = rows[r]
            for col in range(8):
                if b & (0x80 >> col):
                    self.pixel(x + col, y + r, c)

    def invert_rect(self, x, y, w, h):
        for j in range(h):
            yy = y + j
            if yy < 0 or yy >= self.h:
                continue
            for i in range(w):
                xx = x + i
                if xx < 0 or xx >= self.w:
                    continue
                idx = (yy >> 3) * self.w + xx
                self.buf[idx] ^= (1 << (yy & 7))
