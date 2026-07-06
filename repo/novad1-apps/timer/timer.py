# Timer — a kind:py Nova D1 app. A countdown that beeps when it hits zero.
#
# Set mode: turn = +/- 15 s. SELECT starts. Running: SELECT pauses/resumes, BACK
# stops (back to set). At zero it beeps (nova.beep) + posts a notification. Binds to
# the injected `ui` / `ev` / `nova`. MicroPython-safe: no f-strings, .format() only.

TITLE = 'Timer'
CATEGORY = 'Tools'

_STEP = 15
_MAX = 3600


def _fmt(sec):
    """Seconds -> MM:SS. Pure; the tested core."""
    if sec < 0:
        sec = 0
    return '{:02d}:{:02d}'.format(sec // 60, sec % 60)


class Timer(ui.Screen):
    title = 'Timer'

    def __init__(self):
        self.total = 60          # the set duration
        self.left = 0            # remaining while armed/running
        self.run = False
        self.done = False
        self._acc = 0

    def draw(self, c):
        val = self.left if (self.run or self.left or self.done) else self.total
        s = _fmt(val)
        x = max(0, (c.w - len(s) * ui._ADV * 2) // 2)
        c.text(x, ui._TOP + 2, s, 1, 2)
        if self.done:
            foot = 'DONE  SEL/BACK'
        elif self.run:
            foot = 'SEL pause  BACK stop'
        elif self.left:
            foot = 'SEL resume BACK stop'
        else:
            foot = 'turn set  SEL start'
        c.text(2, c.h - ui._FH, foot, 1)

    def tick(self, dt_ms=0):
        if not self.run:
            return False
        self._acc += dt_ms or 16
        if self._acc < 1000:
            return False
        self._acc -= 1000
        self.left -= 1
        if self.left <= 0:
            self.left = 0
            self.run = False
            self.done = True
            try:
                nova.beep(2200, 150)
                nova.notify('Timer done')
            except Exception:
                pass
        return True

    def animating(self):
        return self.run

    def on_event(self, e):
        if self.done:                                  # any key clears the DONE state
            self.done = False
            self.left = 0
            return e if e in (ev.BACK, ev.HOME) else None
        if e == ev.ROT_CW and not self.run and not self.left:
            self.total = min(_MAX, self.total + _STEP)
            return None
        if e == ev.ROT_CCW and not self.run and not self.left:
            self.total = max(_STEP, self.total - _STEP)
            return None
        if e == ev.SELECT:
            if self.run:
                self.run = False                       # pause
            else:
                if not self.left:
                    self.left = self.total             # start fresh
                self.run = True                        # start / resume
                self._acc = 0
            return None
        if e == ev.BACK:
            if self.run or self.left:
                self.run = False
                self.left = 0                          # stop -> back to set mode
                return None
            return 'back'
        if e == ev.HOME:
            return 'home'
        return None


def app():
    return Timer()
