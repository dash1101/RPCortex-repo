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
import novafont5x7 as _f

# Layout tokens — derived from the font so a font swap reflows every screen.
_ADV = _f.ADVANCE               # px per character cell (incl. spacing)
_FH = _f.HEIGHT                 # glyph height
_BARH = _FH + 2                 # status-bar height (+1px so text clears the rule)
_TOP = _BARH + 1                # body starts 1px below the rule
# Row pitch: glyph height + 2px of breathing room. With the compact 5x7 face that's
# a 9px pitch, which still gives 6 rows on a 64px panel (the old 8x8 face only fit
# 5) while leaving the rows visually separated — at +1 they crowded each other.
_ROWH = _FH + 2


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


def strip_ansi(s):
    """Remove ANSI escape sequences from captured shell text.

    Lives in the leaf because every consumer of the shell's capture buffer needs
    it and they are in different modules — the Commands screen in novagui, the
    Shell app in novagui_shell, the web panel in novaweb. The Shell app shipped
    without it and rendered the shell's own '[@]' / '[!]' line markers as raw
    escape sequences, which is what made those symbols come out as garbage on the
    panel while every other screen showed them cleanly.

    A sequence runs from ESC to the first ASCII letter, which covers the colour
    codes (\x1b[96m), the cursor moves and the erases (\x1b[2J, \x1b[K) that the
    TUI commands emit."""
    out = ''
    i = 0
    n = len(s)
    while i < n:
        if s[i] == '\x1b':
            j = i + 1
            while j < n and not ('a' <= s[j] <= 'z' or 'A' <= s[j] <= 'Z'):
                j += 1
            i = j + 1
        else:
            out += s[i]
            i += 1
    return out


def fit(c, x, y, s, col=1):
    """Draw ONE line guaranteed to fit the panel: narrow (proportional) spacing,
    truncated if it still doesn't fit. Use this for any message whose length isn't
    fixed (error strings, status lines, footers) — a plain c.text() at the 8px cell
    silently ran off the right edge, which is what clipped these screens."""
    if not s:
        return
    s = str(s)
    avail = c.w - x
    if c.text_width(s) > avail:
        s = s[:max(0, avail // _ADV)]      # uniform cells -> exact, no re-measuring
    c.text(x, y, s, col)


_SB_W = 3           # scrollbar lane width


def rounded_rect(c, x, y, w, h, col=1):
    """A filled rect with the 4 corner pixels knocked out — a 1px 'radius'. On a
    1-bit panel that's the most curve available, and it visibly softens the
    selection highlight versus a hard white block."""
    if w <= 2 or h <= 2:
        c.fill_rect(x, y, w, h, col)
        return
    c.fill_rect(x + 1, y, w - 2, h, col)          # middle block
    c.fill_rect(x, y + 1, 1, h - 2, col)          # left edge, inset
    c.fill_rect(x + w - 1, y + 1, 1, h - 2, col)  # right edge, inset


def scrollbar(c, x, y, h, top, visible, total):
    """A real scrollbar: a full-height track plus a thumb sized/positioned by how
    much of the list is on screen. Replaces the tiny up/down triangles, which only
    said 'there is more' without showing how much or where you are."""
    if total <= visible or h <= 4:
        return
    c.vline(x + _SB_W // 2, y, h, 1)                       # track
    th = max(4, (h * visible) // total)                    # thumb height
    span = h - th
    ty = y + (span * top) // max(1, (total - visible))
    c.fill_rect(x, ty, _SB_W, th, 1)                       # thumb


def spinner(c, x, y, phase):
    """A small rotating mark for 'busy, please wait'. Four frames (| / - \\) drawn
    as lines so it costs almost nothing — shown whenever the UI is blocked on work
    that can't be interrupted, so the device never looks frozen."""
    p = phase % 4
    if p == 0:
        c.vline(x + 2, y, 5, 1)
    elif p == 1:
        c.line(x, y + 4, x + 4, y, 1)
    elif p == 2:
        c.hline(x, y + 2, 5, 1)
    else:
        c.line(x, y, x + 4, y + 4, 1)


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
        n = len(self.items)
        scrolls = n > rows
        # Leave a lane for the scrollbar only when there IS something to scroll.
        right = c.w - (_SB_W + 1) if scrolls else c.w
        for i in range(rows):
            idx = self.top + i
            if idx >= n:
                break
            label, fac = self.items[idx]
            avail = right - 12
            if c.text_width(label) > avail:
                label = label[:max(0, avail // _ADV)]
            y = _TOP + i * _ROWH
            if idx == self.sel:
                rounded_rect(c, 0, y - 1, right, _ROWH, 1)   # soft highlight
                c.text(4, y, label, 0)
                if fac is not None:
                    c.text(right - _ADV - 2, y, '>', 0)
            else:
                c.text(4, y, label, 1)
                if fac is None:
                    c.text(right - _ADV - 2, y, 'x', 1)
        if scrolls:
            scrollbar(c, right + 1, _TOP, c.h - _TOP, self.top, rows, n)

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
