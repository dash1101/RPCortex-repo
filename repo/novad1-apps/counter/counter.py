# Counter — a kind:py Nova D1 app. A big tally you drive with the encoder.
#
# Turn = +/- 1, SELECT = reset to zero. Binds only to the injected `ui` / `ev`.
# MicroPython-safe: no f-strings, .format() only.

TITLE = 'Counter'
CATEGORY = 'Tools'


class Counter(ui.Screen):
    title = 'Counter'

    def __init__(self):
        self.n = 0

    def draw(self, c):
        c.text(2, ui._TOP, 'Tally', 1)
        s = str(self.n)
        sc = 3 if len(s) <= 5 else 2                 # shrink so big counts still fit
        x = max(0, (c.w - len(s) * ui._ADV * sc) // 2)
        c.text(x, ui._TOP + ui._ROWH, s, 1, sc)
        c.text(2, c.h - ui._FH, 'turn +/-   SEL reset', 1)

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.n += 1
            return None
        if e == ev.ROT_CCW:
            self.n -= 1
            return None
        if e == ev.SELECT:
            self.n = 0
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


def app():
    return Counter()
