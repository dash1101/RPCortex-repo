# Desc: Nova D1 UI leaf — the stable app-facing surface (Screen base + layout + helpers).
# File: /Packages/NovaD1/novaui.py
#
# The LEAF of the UI layer: the Screen protocol, the font-derived layout tokens, and the
# shared draw helpers every screen (and every installed kind:py app) builds on. It
# imports only novainput (events) + novafont (metrics) — never novagui — so screens and
# apps depend on THIS stable surface, not novagui's internals. That is what lets the
# monolith split move screen classes freely, and what a downloaded app binds to.
# See DESIGN.md for the design system these encode.
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import novainput as ev          # re-exported: screens/apps do `from novaui import ev`
import novafont as _f

# Layout tokens — derived from the font so a font swap reflows every screen.
_ADV = _f.ADVANCE               # px per character cell (incl. spacing)
_FH = _f.HEIGHT                 # glyph height
_BARH = _FH + 1                 # status-bar height
_TOP = _BARH + 2                # body starts below the status bar + rule
_ROWH = _FH + 2                 # menu row height (font-agnostic)


class Screen:
    """Base screen. draw(c) paints from _TOP down; tick(dt_ms) returns True only when a
    redraw is needed; on_event(e) returns None / 'back' / 'home' / a new Screen to push."""
    title = 'Screen'

    def draw(self, c):
        pass

    def on_event(self, e):
        if e == ev.BACK:
            return 'back'
        if e == ev.HOME:
            return 'home'
        return None

    def tick(self, dt_ms=0):
        return False

    def animating(self):
        return False


def _wrap(s, ncols):
    # Word-wrap a string into <=ncols-char lines (cheap, for tiny screens).
    out = []
    line = ''
    for word in s.split(' '):
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= ncols:
            line += ' ' + word
        else:
            out.append(line); line = word
        while len(line) > ncols:        # a single long word
            out.append(line[:ncols]); line = line[ncols:]
    if line:
        out.append(line)
    return out or ['']


def _scroll_tri(c, x, y, up):
    """A tiny 5px up/down triangle — a 'more above/below' scroll hint for lists."""
    if up:
        c.hline(x + 2, y, 1)
        c.hline(x + 1, y + 1, 3)
        c.hline(x, y + 2, 5)
    else:
        c.hline(x, y, 5)
        c.hline(x + 1, y + 1, 3)
        c.hline(x + 2, y + 2, 1)


class Menu(Screen):
    """Classic vertical list — a fallback home + the standard sub-menu widget."""
    def __init__(self, title, items):
        self.title = title
        self.items = items            # list of (label, factory_or_None)
        self.sel = 0
        self.top = 0

    def _rows(self, c):
        return (c.h - _TOP) // _ROWH

    def draw(self, c):
        rows = self._rows(c)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.items):
                break
            label, fac = self.items[idx]
            label = label[:(c.w - 14) // _ADV]      # truncate to fit (no overflow)
            y = _TOP + i * _ROWH
            if idx == self.sel:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                c.text(4, y, label, 0)
                if fac is not None:
                    c.text(c.w - _ADV - 2, y, '>', 0)
            else:
                c.text(4, y, label, 1)
                if fac is None:
                    c.text(c.w - _ADV - 2, y, 'x', 1)
        if self.top > 0:
            _scroll_tri(c, c.w - 6, _TOP, True)          # more items above
        if self.top + rows < len(self.items):
            _scroll_tri(c, c.w - 6, c.h - 4, False)      # more items below

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(self.items)
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(self.items)
        elif e == ev.SELECT:
            fac = self.items[self.sel][1]
            return fac() if fac else None
        elif e == ev.BACK:
            return 'back'
        elif e == ev.HOME:
            return 'home'
        return None
