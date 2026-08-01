# Desc: Nova D1 input — logical UI events from the EC11 encoder + 3 buttons.
# File: /Packages/NovaD1/novainput.py
#
# The UI only ever sees logical events, never raw pins — so the framework + the
# PC mock are identical and the physical wiring stays config-driven.
#   Encoder rotate -> ROT_CW / ROT_CCW      Encoder push -> SELECT
#   Button 1 -> BACK    Button 2 -> HOME
# (3 buttons total with the encoder switch; ACTION kept as an alias of SELECT.)
#
# Encoder decode uses Ben Buxton's full-step transition table: it only emits a
# step on a complete, valid quadrature sequence, so contact bounce / half-steps
# are rejected by design (this is the fix for the "unstable / messy" reads). On
# hardware it runs in a hard IRQ -> integer counter (alloc-free); if IRQs can't
# attach it falls back to polling the same table. MicroPython-safe: no f-strings.

# Logical events
ROT_CW  = 'cw'
ROT_CCW = 'ccw'
SELECT  = 'select'
BACK    = 'back'
HOME    = 'home'
ACTION  = SELECT            # alias — there's no 4th button; SELECT doubles as it

# Buxton full-step table. Index = state*4 + ((A<<1)|B). Low 3 bits = next state;
# 0x10 = a CW step, 0x20 = a CCW step. (If your encoder reads reversed, swap the
# enc_a/enc_b pins in config.)
_DIR_CW = 0x10
_DIR_CCW = 0x20
_TTABLE = (
    0x0, 0x2, 0x4, 0x0,            # R_START
    0x3, 0x0, 0x1, 0x10,          # R_CW_FINAL  -> START | CW
    0x3, 0x2, 0x0, 0x0,           # R_CW_BEGIN
    0x3, 0x2, 0x1, 0x0,           # R_CW_NEXT
    0x6, 0x0, 0x4, 0x0,           # R_CCW_BEGIN
    0x6, 0x5, 0x0, 0x20,          # R_CCW_FINAL -> START | CCW
    0x6, 0x5, 0x4, 0x0,           # R_CCW_NEXT
)


class ScriptedSource:
    """Host/mock source: replay a fixed list of events (and None = idle tick)."""
    def __init__(self, events=None):
        self._q = list(events or [])

    def feed(self, events):
        self._q.extend(events)

    def poll(self):
        return self._q.pop(0) if self._q else None


class GpioSource:
    """On-device source: EC11 quadrature (IRQ + table) + debounced buttons.
    Pins come from a config dict so builders wire freely."""
    def __init__(self, pins):
        import machine
        self._machine = machine
        P = machine.Pin
        pu = machine.Pin.PULL_UP
        self.enc_a = P(pins['enc_a'], P.IN, pu)
        self.enc_b = P(pins['enc_b'], P.IN, pu)
        self.btns = {
            SELECT: P(pins['enc_sw'], P.IN, pu),
            BACK:   P(pins['btn1'], P.IN, pu),
            HOME:   P(pins['btn2'], P.IN, pu),
        }
        self._st = (self.enc_a.value() << 1) | self.enc_b.value()
        self._count = 0
        self._last = {k: 1 for k in self.btns}
        self._bt = {k: 0 for k in self.btns}
        self._btn_order = (SELECT, BACK, HOME)   # stable scan order
        self._pending = []                        # button presses awaiting delivery
        self._irq = False
        try:
            trig = P.IRQ_RISING | P.IRQ_FALLING
            self.enc_a.irq(self._isr, trig)
            self.enc_b.irq(self._isr, trig)
            self._irq = True
        except Exception:
            self._irq = False          # fall back to polled decode

    def _isr(self, pin):
        # HARD IRQ — must stay allocation-free: pin reads, tuple index, int math.
        ps = (self.enc_a.value() << 1) | self.enc_b.value()
        st = _TTABLE[(self._st & 0x07) * 4 + ps]
        self._st = st
        if st & _DIR_CW:
            self._count += 1
        elif st & _DIR_CCW:
            self._count -= 1

    def _take_step(self):
        """Consume ONE pending encoder detent. The read-modify-write of _count is
        guarded against the hard IRQ (which also writes it) — without the guard an
        ISR landing mid-update loses a detent, so the UI's selection silently drifts
        out of step with how far the knob was actually turned."""
        m = self._machine
        try:
            s = m.disable_irq()
        except Exception:
            s = None
        try:
            c = self._count
            if c > 0:
                self._count = c - 1
                return ROT_CW
            if c < 0:
                self._count = c + 1
                return ROT_CCW
            return None
        finally:
            if s is not None:
                try:
                    m.enable_irq(s)
                except Exception:
                    pass

    def _poll_encoder(self):
        if not self._irq:              # polled fallback: step the table now
            ps = (self.enc_a.value() << 1) | self.enc_b.value()
            st = _TTABLE[(self._st & 0x07) * 4 + ps]
            self._st = st
            if st & _DIR_CW:
                self._count += 1
            elif st & _DIR_CCW:
                self._count -= 1
        return self._take_step()

    def _scan_buttons(self):
        """Update EVERY button's edge/debounce state and queue any presses.
        Scanning all of them on every poll matters: the old code returned on the
        first press, so the other buttons' release state went stale, and while the
        encoder had queued detents the buttons were never scanned at all — a press
        during a fast spin was dropped entirely."""
        try:
            import utime
            now = utime.ticks_ms()
        except Exception:
            now = 0
        for evt in self._btn_order:
            pin = self.btns[evt]
            v = pin.value()
            if v == 0:
                if self._last[evt] == 1 and (now - self._bt[evt]) > 30:
                    self._last[evt] = 0
                    self._bt[evt] = now
                    self._pending.append(evt)
            else:
                self._last[evt] = 1

    def poll(self):
        # Buttons are scanned every call (never starved by the encoder), but
        # ROTATION is still delivered FIRST so events stay in the order they
        # physically happened — a press queued behind pending detents must act on
        # where the knob ended up, not where it was.
        self._scan_buttons()
        e = self._poll_encoder()
        if e is not None:
            return e
        if self._pending:
            return self._pending.pop(0)
        return None
