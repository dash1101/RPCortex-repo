# Base Convert — a kind:py Nova D1 app. See a value in DEC / HEX / BIN at once.
#
# Turn adjusts the value by the current step; SELECT cycles the step (1/16/256/4096)
# so you can reach any 16-bit number quickly. Binds only to the stable Nova surface
# (`ui`, `ev`) injected by the loader. MicroPython-safe: no f-strings, .format() only.

TITLE = 'Base Conv'
CATEGORY = 'Tools'

_STEPS = (1, 16, 256, 4096)
_MASK = 0xFFFF


def _bases(n):
    """A 16-bit value -> its (decimal, hex, binary) display rows. Pure; the tested core."""
    n &= _MASK
    return ('DEC  {}'.format(n),
            'HEX  {:04X}'.format(n),
            'BIN  {:016b}'.format(n))


class BaseConv(ui.Screen):
    title = 'Base Conv'

    def __init__(self):
        self.n = 0
        self.si = 0

    def draw(self, c):
        for i, row in enumerate(_bases(self.n)):
            c.text(2, ui._TOP + i * ui._ROWH, row, 1)
        c.text(2, c.h - ui._FH, 'turn={}  SEL step'.format(_STEPS[self.si]), 1)

    def on_event(self, e):
        st = _STEPS[self.si]
        if e == ev.ROT_CW:
            self.n = (self.n + st) & _MASK
            return None
        if e == ev.ROT_CCW:
            self.n = (self.n - st) & _MASK
            return None
        if e == ev.SELECT:
            self.si = (self.si + 1) % len(_STEPS)
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


def app():
    return BaseConv()
