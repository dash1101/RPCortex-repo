# Dice — a kind:py Nova D1 app. SELECT rolls, BACK exits.
#
# A full Nova-UI app (not a button grid): it defines a Screen and an app() factory.
# It binds ONLY to the stable Nova surface that the loader injects — `ui` (novaui:
# Screen, layout tokens, helpers) and `ev` (input events) — never novagui internals.
# Optional module-level TITLE (home label) + CATEGORY (home folder).
#
# MicroPython-safe: no f-strings, .format() only.

TITLE = 'Dice'
CATEGORY = 'Tools'


class Dice(ui.Screen):
    title = 'Dice'

    def __init__(self):
        self.n = 1
        self.rolling = 0

    def draw(self, c):
        c.text(2, ui._TOP, 'Dice', 1)
        s = str(self.n)
        c.text(max(0, (c.w - len(s) * ui._ADV * 3) // 2), ui._TOP + ui._ROWH, s, 1, 3)
        foot = 'rolling...' if self.rolling > 0 else 'SELECT roll   BACK exit'
        c.text(2, c.h - ui._FH, foot, 1)

    def tick(self, dt_ms=0):
        if self.rolling > 0:
            self.rolling -= dt_ms or 16
            self.n = (self.n % 6) + 1        # cycle while "rolling" -> settles pseudo-random
            return True
        return False

    def on_event(self, e):
        if e == ev.SELECT:
            self.rolling = 400               # animate ~0.4 s, then settle
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


def app():
    return Dice()
