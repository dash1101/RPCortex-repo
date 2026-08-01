# novaui: the UI leaf / stable app surface. Screen protocol, layout tokens, and the
# Menu widget that screens + installed kind:py apps bind to.
import sys
import _shims
_shims.install()
from _shims import T
import novaui as U
import novainput as ev

t = T('test_novaui')


class _FakeC:
    w = 128
    h = 64
    def __init__(self):
        self.calls = []
    def text(self, *a, **k):
        self.calls.append(('text',) + a)
    def fill_rect(self, *a, **k):
        self.calls.append(('fill',) + a)
    def hline(self, *a, **k):
        self.calls.append(('hline',) + a)
    def text_width(self, s, scale=1, narrow=False):
        # Mirrors Canvas: narrow text is proportional (~5px/char here), fixed cell
        # is 8px. Menu/fit() measure with this to keep rows inside the panel.
        return len(s) * (5 if narrow else 8) * scale


# layout tokens are sane integers derived from the font
for name in ('_ADV', '_FH', '_BARH', '_TOP', '_ROWH'):
    v = getattr(U, name)
    t.ok(isinstance(v, int) and v > 0, '{} is a positive int'.format(name))
t.ok(U._TOP > U._BARH, 'body starts below the status bar')

# Screen base contract
s = U.Screen()
t.eq(s.on_event(ev.BACK), 'back', 'Screen BACK -> back')
t.eq(s.on_event(ev.HOME), 'home', 'Screen HOME -> home')
t.eq(s.on_event(ev.SELECT), None, 'Screen SELECT -> None by default')
t.ok(not s.tick(16), 'a still screen needs no redraw')

# _wrap word-wraps within the column budget
w = U._wrap('the quick brown fox jumps', 10)
t.ok(all(len(line) <= 10 for line in w), '_wrap respects the width')
t.ok(len(U._wrap('supercalifragilistic', 6)) >= 3, '_wrap breaks a long word')

# _scroll_tri draws (up + down variants) without error
c = _FakeC()
U._scroll_tri(c, 100, 10, True)
U._scroll_tri(c, 100, 50, False)
t.ok(len(c.calls) == 6, '_scroll_tri draws both triangles')

# Menu navigation + selection
picked = []
m = U.Menu('Test', [('Alpha', lambda: picked.append('a')), ('Beta', None)])
m.draw(_FakeC())                            # renders without error
t.eq(m.sel, 0, 'menu starts at top')
m.on_event(ev.ROT_CW)
t.eq(m.sel, 1, 'turn moves the cursor')
m.on_event(ev.ROT_CW)
t.eq(m.sel, 0, 'cursor wraps around')
m.on_event(ev.SELECT)
t.eq(picked, ['a'], 'SELECT runs the item factory')
t.eq(m.on_event(ev.BACK), 'back', 'Menu BACK -> back')

sys.exit(t.done())
