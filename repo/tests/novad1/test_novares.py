# Resources screen: the live readout in Tools.
#
# The thing worth testing here is the FORMATTING, not the readings. The panel is 20
# characters wide, and a value that overflows is silently trimmed — which on a
# "used / total" figure drops the digits that carry the meaning and leaves
# something that still looks like a number. So every row this screen can produce is
# checked against the width it has to live in.
import sys
import _shims
_shims.install()
from _shims import T

import novacanvas
import novagui_res as R

t = T('test_novares')

# ------------------------------------------------------------------ formatting
t.eq(R._kb(0), '0B', 'zero bytes')
t.eq(R._kb(512), '512B', 'under a kilobyte stays in bytes')
t.eq(R._kb(2048), '2K', 'kilobytes')
t.eq(R._kb(1024 * 1024 * 3 // 2), '1.5M', 'megabytes keep one decimal')
t.eq(R._kb('nonsense'), '?', 'an unreadable size is ? rather than a traceback')
t.eq(R._kb(None), '?', 'and so is None')

t.eq(R._pair(120 * 1024, 264 * 1024), '120/264K', 'both figures share one suffix')
t.eq(R._pair(0, 512), '0/512B', 'small totals stay in bytes')
t.eq(R._pair(1024 * 1024, 4 * 1024 * 1024), '1.0/4.0M', 'megabyte pairs')
t.eq(R._pair('x', 1), '?', 'an unreadable pair is ?')

t.eq(R._pct(50, 100), 50, 'percentage')
t.eq(R._pct(1, 0), 0, 'a zero total is 0%, not a ZeroDivisionError')

# ------------------------------------------------------------------- the rows
c = novacanvas.Canvas(128, 64)
rows = R.snapshot(c)
t.ok(rows, 'snapshot returns rows')
t.ok(all(isinstance(r, tuple) and len(r) == 2 for r in rows),
     'every row is a (label, value) pair')
t.ok(all(isinstance(r[0], str) and isinstance(r[1], str) for r in rows),
     'both halves are already strings -- draw() does no formatting')

labels = [lbl for lbl, _v in rows]
for want in ('WiFi', 'Nearby', 'Incognito', 'Screen', 'CPU'):
    t.ok(want in labels, 'the {} row is present'.format(want))

# The user asked for screen specs; the size must come from the live canvas, so a
# canvas of a different size must be reported as that size.
spec = dict(rows)['Screen']
t.ok('128x64' in spec, 'screen spec reports the panel size')
big = R.snapshot(novacanvas.Canvas(128, 32))
t.ok('128x32' in dict(big)['Screen'],
     'the size is read from the canvas, not from a constant')

# ---------------------------------------------------------------- row widths
# 20 columns at the shipped font. label + a space + value must fit, or the row is
# trimmed and the reading becomes a lie.
COLS = 20
for lbl, val in rows:
    if lbl in ('WiFi', 'IP', 'Disk', 'Nearby'):
        continue        # genuinely variable: an SSID or a host-sized filesystem
    t.ok(len(lbl) + 1 + len(val) <= COLS,
         'row "{}" fits 20 columns (got {})'.format(lbl, len(lbl) + 1 + len(val)))

# ------------------------------------------------------------------- the screen
s = R.ResourcesScreen()
s.draw(c)
t.ok(s.rows, 'draw() populates the rows on first paint')

# The refresh drops the cached rows so draw() rebuilds them with a real canvas --
# holding a canvas reference alive for the life of the screen would be the
# alternative, and this device is short of RAM, not of redraws.
s.tick(R._REFRESH_MS)
t.eq(s.rows, [], 'a refresh clears the cache instead of caching the canvas')
s.draw(c)
t.ok(s.rows, 'and the next paint rebuilds them')

import novainput as ev
s.top = 0
s.on_event(ev.ROT_CCW)
t.eq(s.top, 0, 'scrolling up at the top does not go negative')
before = s.top
s.on_event(ev.ROT_CW)
t.ok(s.top > before, 'scrolling down moves')
s.top = 999
s.draw(c)
t.ok(s.top <= max(0, len(s.rows) - s._visible(c)),
     'draw clamps a scroll position past the end')

t.eq(s.on_event(ev.HOME), ev.HOME, 'HOME leaves')
t.eq(s.on_event(ev.BACK), ev.BACK, 'BACK leaves')

# ------------------------------------------------------- no radios are touched
# Opening a readout screen must not start a scan or bring an interface up. That
# was the whole point of the privacy pass: nothing initiates radio traffic
# without the user asking for it.
import inspect
src = inspect.getsource(R)
for banned in ('.scan(', 'active(True)', '.connect('):
    t.ok(banned not in src,
         'Resources never calls {} -- a readout must not cause radio traffic'
         .format(banned))

sys.exit(t.done())
