# Desc: Nova D1 UI framework — status bar, menus, screen stack, cancel-anything.
# File: /Packages/NovaD1/novagui.py
#
# Modular UI for the 128x64 OLED. Draws via novacanvas (so device == PC mock).
# The runner owns a screen STACK + the always-on status bar (WiFi / battery /
# clock). Every screen's on_event() returns one of: None, 'back', 'home', or a
# new Screen to push. Long-running actions poll .cancelled so they can be quit at
# any time (BACK), keeping the cooperative-multitasking promise.
#
# MicroPython-safe: no f-strings, positional split, .format() only.

import novainput as ev

_TOP = 11          # body starts below the status bar
_ROWH = 9          # menu row height


# --- status-bar icons (drawn with primitives — no bitmap blobs to maintain) ---
def _wifi(c, x, y, connected):
    # three ascending bars; filled when connected, baseline-only when not.
    for i in range(3):
        bx = x + i * 3
        h = 2 + i * 2
        if connected:
            c.fill_rect(bx, y + (6 - h), 2, h, 1)
        else:
            c.pixel(bx, y + 5, 1); c.pixel(bx + 1, y + 5, 1)


def _battery(c, x, y, pct):
    c.rect(x, y, 11, 6, 1)            # body
    c.fill_rect(x + 11, y + 2, 1, 2, 1)  # nub
    fillw = (pct * 9) // 100
    if fillw > 0:
        c.fill_rect(x + 1, y + 1, fillw, 4, 1)


def draw_status_bar(c, state):
    title = state.get('title', 'Nova D1')
    c.text(2, 1, title[:11], 1)
    _wifi(c, 74, 1, state.get('wifi', False))
    _battery(c, 86, 1, state.get('battery', 50))
    c.text(100, 1, state.get('time', '--:--'), 1)
    c.hline(0, 9, c.w, 1)


# --- screens ----------------------------------------------------------------
class Screen:
    title = 'Screen'

    def draw(self, c):
        pass

    def on_event(self, e):
        if e == ev.BACK:
            return 'back'
        if e == ev.HOME:
            return 'home'
        return None

    def tick(self):
        pass


class Menu(Screen):
    def __init__(self, title, items):
        # items: list of (label, factory_or_None). factory() -> Screen, or None.
        self.title = title
        self.items = items
        self.sel = 0
        self.top = 0

    def _visible_rows(self, c):
        return (c.h - _TOP) // _ROWH

    def draw(self, c):
        rows = self._visible_rows(c)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.items):
                break
            label, fac = self.items[idx]
            y = _TOP + i * _ROWH
            if idx == self.sel:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                c.text(4, y, label, 0)
                if fac is not None:                # affordance: drills in
                    c.text(c.w - 8, y, '>', 0)
            else:
                c.text(4, y, label, 1)
                if fac is None:
                    c.text(c.w - 9, y, 'x', 1)     # greyed/absent marker

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(self.items)
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(self.items)
        elif e == ev.SELECT:
            fac = self.items[self.sel][1]
            return fac() if fac else None
        elif e == ev.BACK:
            return 'back'
        elif e == ev.HOME:
            return 'home'
        return None


class RunningScreen(Screen):
    """A long action (e.g., a scan or a script). Demonstrates cancel-anything:
    BACK sets .cancelled; the worker polls it and bails. Shows a progress bar."""
    def __init__(self, title, total=100):
        self.title = title
        self.total = total
        self.progress = 0
        self.cancelled = False
        self.done = False

    def draw(self, c):
        c.text(4, _TOP + 2, self.title[:20], 1)
        if self.done:
            c.text(4, _TOP + 14, 'Done.' if not self.cancelled else 'Cancelled.', 1)
        else:
            bx, by, bw = 6, _TOP + 16, c.w - 12
            c.rect(bx, by, bw, 8, 1)
            fw = (self.progress * (bw - 2)) // max(1, self.total)
            c.fill_rect(bx + 1, by + 1, fw, 6, 1)
            pct = (self.progress * 100) // max(1, self.total)
            c.text(4, by + 12, '{}%'.format(pct), 1)
        c.text(4, c.h - 8, 'BACK = cancel' if not self.done else 'BACK = exit', 1)

    def step(self, n=1):
        if not self.done and not self.cancelled:
            self.progress += n
            if self.progress >= self.total:
                self.progress = self.total
                self.done = True

    def on_event(self, e):
        if e == ev.BACK:
            if not self.done:
                self.cancelled = True
                self.done = True
                return None          # stay to show "Cancelled.", BACK again exits
            return 'back'
        if e == ev.HOME:
            return 'home'
        return None


# --- the runner -------------------------------------------------------------
class NovaUI:
    def __init__(self, display, canvas, source, state_provider, home):
        self.display = display
        self.canvas = canvas
        self.source = source
        self.state = state_provider
        self.stack = [home]

    def render(self):
        c = self.canvas
        c.clear(0)
        st = self.state() if callable(self.state) else dict(self.state)
        st['title'] = self.stack[-1].title
        draw_status_bar(c, st)
        self.stack[-1].draw(c)
        self.display.show(c)

    def handle(self, e):
        if e is None:
            return
        r = self.stack[-1].on_event(e)
        if r == 'back':
            if len(self.stack) > 1:
                self.stack.pop()
        elif r == 'home':
            del self.stack[1:]
        elif isinstance(r, Screen):
            self.stack.append(r)

    def run(self, sleep_ms=30):
        # Synchronous on-device loop (direct/foreground test).
        try:
            import utime as _t
            _sleep = _t.sleep_ms
        except ImportError:
            import time as _tt
            def _sleep(ms): _tt.sleep(ms / 1000.0)
        self._stop = False
        self.render()
        while not self._stop:
            e = self.source.poll()
            if e is not None:
                self.handle(e)
                self.render()
            else:
                self.stack[-1].tick()
            _sleep(sleep_ms)

    async def run_async(self, sleep_ms=30):
        # Cooperative loop — run as a BACKGROUND SERVICE so the serial shell stays
        # free (the OLED and the shell are separate surfaces). Yields every tick.
        import asyncio
        self._stop = False
        self.render()
        while not self._stop:
            e = self.source.poll()
            if e is not None:
                self.handle(e)
                self.render()
            else:
                self.stack[-1].tick()
            await asyncio.sleep_ms(sleep_ms)

    def stop(self):
        self._stop = True


# --- home screen (apps appear per present module; greyed when absent) --------
def build_home(modules=None):
    """modules: dict name->present(bool). Absent ones show greyed (no drill)."""
    modules = modules or {}

    def present(name):
        return modules.get(name, True)

    def scan_screen():
        return RunningScreen('Sub-GHz: scanning', total=100)

    items = [
        ('NFC / RFID',  (lambda: Menu('NFC / RFID', [('Read tag', None), ('Emulate', None), ('Back', None)])) if present('nfc') else None),
        ('Sub-GHz',     scan_screen if present('subghz') else None),
        ('Infrared',    (lambda: Menu('Infrared', [('Send', None), ('Receive', None)])) if present('ir') else None),
        ('LoRa',        (lambda: Menu('LoRa', [('Send', None), ('Listen', None)])) if present('lora') else None),
        ('GPS',         (lambda: Menu('GPS', [('Fix', None), ('Wardrive', None)])) if present('gps') else None),
        ('Scripts',     lambda: Menu('Scripts', [('hello.rps', None), ('blink.py', None)])),
        ('Settings',    lambda: Menu('Settings', [('Brightness', None), ('WiFi', None), ('Time', None), ('Modules', None)])),
    ]
    return Menu('Nova D1', items)
