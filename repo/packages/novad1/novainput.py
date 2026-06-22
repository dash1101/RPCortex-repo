# Desc: Nova D1 input — logical UI events from the EC11 encoder + 3 buttons.
# File: /Packages/NovaD1/novainput.py
#
# The UI only ever sees logical events, never raw pins — so the framework + the
# PC mock are identical and the physical wiring stays config-driven.
#   Encoder rotate -> ROT_CW / ROT_CCW      Encoder push -> SELECT
#   Button 1 -> BACK    Button 2 -> HOME    Button 3 -> ACTION
# (mapping is remappable; this is the proposed default from the dev plan.)
#
# MicroPython-safe: no f-strings, positional split, .format() only.

# Logical events
ROT_CW  = 'cw'
ROT_CCW = 'ccw'
SELECT  = 'select'
BACK    = 'back'
HOME    = 'home'
ACTION  = 'action'


class ScriptedSource:
    """Host/mock source: replay a fixed list of events (and None = idle tick)."""
    def __init__(self, events=None):
        self._q = list(events or [])

    def feed(self, events):
        self._q.extend(events)

    def poll(self):
        return self._q.pop(0) if self._q else None


class GpioSource:
    """On-device source: EC11 quadrature + 3 debounced buttons. Pins come from a
    config dict so builders wire freely. (Structure is final; quadrature timing
    gets tuned during hardware bring-up.)"""
    def __init__(self, pins):
        import machine
        self._machine = machine
        P = machine.Pin
        pu = machine.Pin.PULL_UP
        self.enc_a = P(pins['enc_a'], P.IN, pu)
        self.enc_b = P(pins['enc_b'], P.IN, pu)
        self.btns = {
            SELECT: P(pins['enc_sw'], P.IN, pu),
            BACK:   P(pins['btn1'],  P.IN, pu),
            HOME:   P(pins['btn2'],  P.IN, pu),
            ACTION: P(pins['btn3'],  P.IN, pu),
        }
        self._last_a = self.enc_a.value()
        self._last = {k: 1 for k in self.btns}

    def poll(self):
        # Encoder: on a falling edge of A, B's level gives direction.
        a = self.enc_a.value()
        if a != self._last_a:
            self._last_a = a
            if a == 0:
                return ROT_CW if self.enc_b.value() else ROT_CCW
        # Buttons: active-low, report on press edge.
        for ev, pin in self.btns.items():
            v = pin.value()
            if v == 0 and self._last[ev] == 1:
                self._last[ev] = 0
                return ev
            if v == 1:
                self._last[ev] = 1
        return None
