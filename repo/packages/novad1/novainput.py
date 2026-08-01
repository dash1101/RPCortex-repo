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
SELECT_HOLD = 'selecthold'  # SELECT held past HOLD_MS (a shortcut, e.g. keyboard OK)
HOME_HOLD   = 'homehold'    # HOME held past HOLD_MS -> the power screen, always

HOLD_MS = 600               # press longer than this counts as a hold
DEBOUNCE_MS = 25            # contact chatter shorter than this is not a real edge

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

    def held_ms(self, evt):
        return 0


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
        self._holds = {}                          # evt -> hold already fired
        self._irq = False

        # --- interrupt-driven button capture ---------------------------------
        # Polling alone LOSES TAPS. The UI loop naps 250-400 ms when idle, and it
        # samples the pins once per iteration, so a normal press that starts and
        # ends inside one nap is never seen at all — which is why a button
        # sometimes did nothing until it was pressed again and held. An edge
        # interrupt cannot miss it however long the loop sleeps.
        #
        # Everything below is allocation-free, because these run in a HARD IRQ:
        # bytearray/list stores, small-int arithmetic, and function references
        # bound up front (an `import` inside an ISR would allocate).
        import utime
        self._ticks = utime.ticks_ms
        self._tdiff = utime.ticks_diff
        self._counts = bytearray(6)        # [tap, hold] per button, in _btn_order
        self._down = [0, 0, 0]             # press timestamp per button
        self._up = [0, 0, 0]               # release timestamp per button
        self._is_down = bytearray(3)
        # Set when the POLL has already reported a hold for a button that is
        # still down, so the ISR does not report it a second time on release.
        self._reported = bytearray(3)
        self._btn_irq = False
        try:
            trig = P.IRQ_RISING | P.IRQ_FALLING
            for i, evt in enumerate(self._btn_order):
                self.btns[evt].irq(self._mk_btn_isr(i), trig)
            self._btn_irq = True
        except Exception:
            self._btn_irq = False          # fall back to the polled scan
        try:
            trig = P.IRQ_RISING | P.IRQ_FALLING
            self.enc_a.irq(self._isr, trig)
            self.enc_b.irq(self._isr, trig)
            self._irq = True
        except Exception:
            self._irq = False          # fall back to polled decode

    def _mk_btn_isr(self, idx):
        """One handler per button, built ONCE here so the ISR itself closes over
        an integer index and allocates nothing."""
        pin = self.btns[self._btn_order[idx]]
        counts = self._counts
        down = self._down
        up = self._up
        is_down = self._is_down
        reported = self._reported
        ticks = self._ticks
        tdiff = self._tdiff

        def _isr(_p):
            # HARD IRQ — no allocation, no imports, no exceptions.
            #
            # DEBOUNCED. A mechanical switch chatters for a few milliseconds on
            # both edges, so one press produces a burst of press/release pairs.
            # Undebounced, every one of those counted as a separate tap — which
            # is why a single press sometimes fired twice. The polled scan this
            # replaced had a 30 ms guard; dropping it was the regression.
            #
            # Bounce is rejected by DURATION rather than by ignoring edges
            # outright: an edge is only believed once the button has been in its
            # new state longer than a bounce lasts. Ignoring edges by timestamp
            # would swallow the genuine release of a fast tap.
            t = ticks()
            if pin.value() == 0:                 # pressed (active-low)
                if is_down[idx] == 0:
                    if tdiff(t, up[idx]) < DEBOUNCE_MS:
                        return                   # chatter after the last release
                    is_down[idx] = 1
                    reported[idx] = 0
                    down[idx] = t
                    if idx == 1:                 # BACK reports on the press edge
                        if counts[2] < 250:
                            counts[2] += 1
            else:                                # released
                if is_down[idx] == 1:
                    dt = tdiff(t, down[idx])
                    if dt < DEBOUNCE_MS:
                        return                   # chatter — treat it as still down
                    is_down[idx] = 0
                    up[idx] = t
                    if reported[idx]:            # the poll already fired the hold
                        reported[idx] = 0
                    elif idx != 1:               # SELECT/HOME report on release,
                        k = idx * 2 + (1 if dt >= HOLD_MS else 0)
                        if counts[k] < 250:
                            counts[k] += 1
        return _isr

    def _drain_buttons(self):
        """Move whatever the interrupts recorded into the pending queue, and fire
        a hold for a button still held past HOLD_MS.

        The hold has to come from here rather than the ISR: HOME_HOLD opens the
        power screen and must fire WHILE the button is down, not when it is let
        go."""
        counts = self._counts
        if len(self._pending) > 32:
            # A stuck or chattering button must not grow this without bound. 32
            # queued presses is already far more than anyone meant.
            del self._pending[:-32]
        for i, evt in enumerate(self._btn_order):
            n = counts[i * 2]
            if n:
                counts[i * 2] = 0
                for _ in range(n):
                    self._pending.append(evt)
            n = counts[i * 2 + 1]
            if n:
                counts[i * 2 + 1] = 0
                hold = SELECT_HOLD if evt == SELECT else (
                    HOME_HOLD if evt == HOME else evt)
                for _ in range(n):
                    self._pending.append(hold)
            # Still held, and long enough? Fire the hold NOW, once — HOME_HOLD
            # opens the power screen, and waiting for the release would make the
            # gesture feel broken. _reported tells the ISR not to count it again.
            if self._is_down[i] and not self._reported[i]:
                if self._tdiff(self._ticks(), self._down[i]) >= HOLD_MS:
                    self._reported[i] = 1
                    if evt == SELECT:
                        self._pending.append(SELECT_HOLD)
                    elif evt == HOME:
                        self._pending.append(HOME_HOLD)

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
        during a fast spin was dropped entirely.

        SELECT is special: it reports on RELEASE, so a long press can be told apart
        from a tap and emit SELECT_HOLD instead. BACK/HOME still fire on the press
        edge, so navigation stays instant."""
        try:
            import utime
            now = utime.ticks_ms()
        except Exception:
            now = 0
        for evt in self._btn_order:
            pin = self.btns[evt]
            v = pin.value()
            if v == 0:                                  # held down
                if self._last[evt] == 1 and (now - self._bt[evt]) > 30:
                    self._last[evt] = 0
                    self._bt[evt] = now
                    if evt == BACK:
                        self._pending.append(evt)       # instant: BACK stays snappy
                elif self._last[evt] == 0 and not self._holds.get(evt) \
                        and (now - self._bt[evt]) >= HOLD_MS:
                    self._holds[evt] = True             # fire each hold once
                    if evt == SELECT:
                        self._pending.append(SELECT_HOLD)
                    elif evt == HOME:
                        self._pending.append(HOME_HOLD)
            else:                                       # released
                if self._last[evt] == 0 and evt in (SELECT, HOME) \
                        and not self._holds.get(evt):
                    self._pending.append(evt)           # a tap -> reported on release
                self._holds[evt] = False
                self._last[evt] = 1

    def held_ms(self, evt):
        """How long `evt`'s button has been held right now, in ms; 0 if it is up.

        Lets the UI show a gesture IN PROGRESS rather than only its result — a
        hold that gives no feedback until it fires feels like nothing happened."""
        try:
            i = self._btn_order.index(evt)
        except ValueError:
            return 0
        if not self._is_down[i]:
            return 0
        return self._tdiff(self._ticks(), self._down[i])

    def poll(self):
        # Buttons are scanned every call (never starved by the encoder), but
        # ROTATION is still delivered FIRST so events stay in the order they
        # physically happened — a press queued behind pending detents must act on
        # where the knob ended up, not where it was.
        if self._btn_irq:
            self._drain_buttons()          # never misses a tap, whatever the nap
        else:
            self._scan_buttons()           # polled fallback
        e = self._poll_encoder()
        if e is not None:
            return e
        if self._pending:
            return self._pending.pop(0)
        return None
