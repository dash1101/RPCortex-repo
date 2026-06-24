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

    def rect(self, x, y, w, h, c=1):
        self.hline(x, y, w, c); self.hline(x, y + h - 1, w, c)
        self.vline(x, y, h, c); self.vline(x + w - 1, y, h, c)

    def fill_rect(self, x, y, w, h, c=1):
        for j in range(h):
            self.hline(x, y + j, w, c)

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
