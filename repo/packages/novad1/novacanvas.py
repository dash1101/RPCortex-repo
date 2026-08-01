# Desc: Nova D1 UI canvas — 1-bit MONO_VLSB framebuffer + drawing primitives.
# File: /Packages/NovaD1/novacanvas.py
#
# The buffer layout is MONO_VLSB — exactly what the SH1106/SSD1306 page memory
# expects — so a driver just streams `buf` out.
#   byte index = (y >> 3) * width + x   ;   bit = 1 << (y & 7)   (a column of 8px)
#
# SPEED: on-device the heavy primitives (fill/pixel/line/rect/blit) run through
# MicroPython's native C `framebuf` module, which wraps the SAME bytearray with
# the SAME MONO_VLSB layout — so the output is byte-identical to the pure-Python
# path, but a full-screen redraw is ~10-50x faster (the difference between a
# choppy ~4fps UI and a smooth one, and it stops a redraw from starving the
# shared event loop). Text keeps the custom 6x8 novafont via a cached GLYPH BLIT
# (each glyph rendered once into a tiny FrameBuffer, then C-blitted), so device
# == mock visually. On CPython (the PC mock render) `framebuf` is absent, so it
# transparently falls back to the pure-Python primitives below — pixel-true.
# MicroPython-safe: no f-strings, positional split, .format() only.

import novafont as _f

_GW = {}        # glyph ink-width cache (narrow/proportional text)

try:
    import framebuf as _fb
    _HAVE_FB = True
except ImportError:
    _fb = None
    _HAVE_FB = False


class Canvas:
    def __init__(self, w=128, h=64):
        self.w = w
        self.h = h
        self.pages = h // 8
        self.buf = bytearray(w * self.pages)
        # Native framebuf over the SAME buffer (MONO_VLSB) when available.
        if _HAVE_FB:
            self.fb = _fb.FrameBuffer(self.buf, w, h, _fb.MONO_VLSB)
        else:
            self.fb = None
        self._glyphs = {}               # code -> tiny FrameBuffer (lit-pixel blit)

    def clear(self, c=0):
        if self.fb is not None:
            self.fb.fill(1 if c else 0)
            return
        v = 0xff if c else 0x00
        for i in range(len(self.buf)):
            self.buf[i] = v

    def pixel(self, x, y, c=1):
        if self.fb is not None:
            self.fb.pixel(x, y, c)
            return
        if x < 0 or x >= self.w or y < 0 or y >= self.h:
            return
        idx = (y >> 3) * self.w + x
        bit = 1 << (y & 7)
        if c:
            self.buf[idx] |= bit
        else:
            self.buf[idx] &= (~bit) & 0xff

    def hline(self, x, y, n, c=1):
        if self.fb is not None:
            self.fb.hline(x, y, n, c)
            return
        for i in range(n):
            self.pixel(x + i, y, c)

    def vline(self, x, y, n, c=1):
        if self.fb is not None:
            self.fb.vline(x, y, n, c)
            return
        for i in range(n):
            self.pixel(x, y + i, c)

    def line(self, x0, y0, x1, y1, c=1):
        if self.fb is not None:
            self.fb.line(x0, y0, x1, y1, c)
            return
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
        if self.fb is not None:
            self.fb.rect(x, y, w, h, c)
            return
        self.hline(x, y, w, c); self.hline(x, y + h - 1, w, c)
        self.vline(x, y, h, c); self.vline(x + w - 1, y, h, c)

    def fill_rect(self, x, y, w, h, c=1):
        if self.fb is not None:
            self.fb.fill_rect(x, y, w, h, c)
            return
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
        # Calls self.pixel — fast automatically when framebuf-backed.
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

    def _glyph(self, code, gi):
        # Build (once) a tiny WIDTHx8 MONO_VLSB FrameBuffer for this glyph. The
        # novafont DATA is ALREADY column-major MONO_VLSB (DATA[gi+col] is the
        # column byte, bit 1<<row = pixel), so it IS a valid glyph buffer.
        g = self._glyphs.get(code)
        if g is None:
            gbuf = bytearray(_f.DATA[gi:gi + _f.WIDTH])
            g = _fb.FrameBuffer(gbuf, _f.WIDTH, 8, _fb.MONO_VLSB)
            self._glyphs[code] = g          # keeps gbuf alive too
        return g

    def char(self, x, y, code, c=1, scale=1):
        if code < _f.FIRST or code > _f.FIRST + 0x5e:
            code = ord('?')
        gi = (code - _f.FIRST) * _f.WIDTH
        # Fast path: normal (c=1, scale=1) text -> one C blit, key=0 so only the
        # lit pixels draw (transparent background, matching the per-pixel path).
        if self.fb is not None and c and scale == 1:
            self.fb.blit(self._glyph(code, gi), x, y, 0)
            return
        # Fallback: c=0 (knockout text on a filled row), scaled text, or no
        # framebuf. pixel()/fill_rect() are still C-fast when framebuf-backed.
        for col in range(_f.WIDTH):
            bits = _f.DATA[gi + col]
            for row in range(_f.HEIGHT):
                if bits & (1 << row):
                    if scale == 1:
                        self.pixel(x + col, y + row, c)
                    else:
                        self.fill_rect(x + col * scale, y + row * scale, scale, scale, c)

    def glyph_w(self, code):
        """Ink width of a glyph (trailing blank columns trimmed), min 1. Cached —
        this runs per character in narrow text."""
        w = _GW.get(code)
        if w is not None:
            return w
        if code < _f.FIRST or code > _f.FIRST + 0x5e:
            code = ord('?')
        gi = (code - _f.FIRST) * _f.WIDTH
        w = 0
        for col in range(_f.WIDTH):
            if _f.DATA[gi + col]:
                w = col + 1
        if code == 0x20:                 # space keeps a sensible width
            w = 3
        w = w or 1
        _GW[code] = w
        return w

    def text(self, x, y, s, c=1, scale=1, narrow=False):
        """Draw text. narrow=True uses PROPORTIONAL spacing (each glyph advances by
        its own ink width + 1px) instead of the fixed 8px cell — same glyphs, so
        legibility is untouched, but a line fits roughly a quarter more characters.
        Used where space is tight (status bar, menu rows)."""
        cx = x
        for ch in s:
            code = ord(ch)
            self.char(cx, y, code, c, scale)
            if narrow:
                cx += (self.glyph_w(code) + 1) * scale
            else:
                cx += _f.ADVANCE * scale

    def text_width(self, s, scale=1, narrow=False):
        if narrow:
            return sum(self.glyph_w(ord(ch)) + 1 for ch in s) * scale
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
