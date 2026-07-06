# Flashlight — a kind:py Nova D1 app. Drives the status LED (WS2812) as a torch.
#
# Turn = brightness, SELECT = on/off. The LED is turned off when you leave. Binds to
# the injected `ui` / `ev` / `nova` (nova.led). MicroPython-safe: no f-strings.

TITLE = 'Torch'
CATEGORY = 'Tools'


class Torch(ui.Screen):
    title = 'Torch'

    def __init__(self):
        self.pct = 60
        self.on = False
        self._apply()

    def _apply(self):
        v = int(self.pct * 255 / 100) if self.on else 0
        try:
            nova.led(v, v, v)                        # white = equal r/g/b
        except Exception:
            pass

    def draw(self, c):
        c.text(2, ui._TOP, 'Flashlight', 1)
        bx, by, bw = 6, ui._TOP + ui._ROWH, c.w - 12
        c.rect(bx, by, bw, 11, 1)
        c.fill_rect(bx + 2, by + 2, int((bw - 4) * self.pct / 100), 7, 1)
        c.text(2, by + 14, '{}%   {}'.format(self.pct, 'ON' if self.on else 'off'), 1)
        c.text(2, c.h - ui._FH, 'turn=level SEL on/off', 1)

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.pct = min(100, self.pct + 10)
            self._apply()
            return None
        if e == ev.ROT_CCW:
            self.pct = max(10, self.pct - 10)
            self._apply()
            return None
        if e == ev.SELECT:
            self.on = not self.on
            self._apply()
            return None
        if e in (ev.BACK, ev.HOME):
            self.on = False
            self._apply()                            # never leave the torch on
            return e
        return None


def app():
    return Torch()
