# Desc: Nova D1 UI framework — status bar, rotating shelf, screens, render loop.
# File: /Packages/NovaD1/novagui.py
#
# Modular UI for the 128x64 OLED. Draws via novacanvas (so device == PC mock).
# The runner owns a screen STACK + the always-on status bar (WiFi / battery /
# clock) and RE-RENDERS ON A TIMER so the clock/signal stay live even with no
# input. The home is a Shelf (animated carousel); sub-screens are full-screen.
# Every screen's on_event() returns one of: None, 'back', 'home', or a new Screen
# to push. Long actions poll .cancelled so they can be quit any time (BACK).
#
# Layout is derived from the font's ADVANCE/HEIGHT, so swapping the font never
# re-breaks the status bar (the 5x7->6x8 bug). MicroPython-safe: no f-strings.

import novainput as ev
import novafont as _f
import novacanvas  # noqa  (kept for symmetry; canvas is passed in)

_ADV = _f.ADVANCE          # px per character cell (incl. spacing)
_FH = _f.HEIGHT            # glyph height
_BARH = _FH + 1            # status-bar height
_TOP = _BARH + 2           # body starts below the status bar + rule
_ROWH = _FH + 2            # menu row height (font-agnostic)


def _reg(key, default=None):
    try:
        import regedit
        v = regedit.read(key)
        return v if v not in (None, '') else default
    except Exception:
        return default


def _save_reg(key, value):
    try:
        import regedit
        regedit.save(key, value)
        return True
    except Exception:
        return False


# --- status-bar icons (primitives — no bitmap blobs to maintain) ------------
def _wifi(c, x, y, connected):
    for i in range(3):
        bx = x + i * 3
        h = 2 + i * 2
        if connected:
            c.fill_rect(bx, y + (6 - h), 2, h, 1)
        else:
            c.pixel(bx, y + 5, 1); c.pixel(bx + 1, y + 5, 1)


def _battery(c, x, y, pct):
    c.rect(x, y, 11, 6, 1)
    c.fill_rect(x + 11, y + 2, 1, 2, 1)
    fillw = (pct * 9) // 100
    if fillw > 0:
        c.fill_rect(x + 1, y + 1, fillw, 4, 1)


def draw_status_bar(c, state):
    # Right-aligned clock, then battery + wifi leftward, then the title fills the
    # rest — all measured from _ADV so a font change can't clip the clock.
    w = c.w
    tstr = state.get('time', '--:--')
    tx = w - len(tstr) * _ADV
    c.text(tx, 1, tstr, 1)
    bx = tx - 12 - 3
    _battery(c, bx, 2, state.get('battery', 50))
    wx = bx - 8 - 3
    _wifi(c, wx, 2, state.get('wifi', False))
    title = state.get('title', 'Nova D1')
    maxc = max(1, (wx - 4) // _ADV)
    c.text(2, 1, title[:maxc], 1)
    c.hline(0, _BARH, w, 1)


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

    def tick(self, dt_ms=0):
        # Return True if the screen changed and needs a redraw.
        return False

    def animating(self):
        return False


def _wrap(s, ncols):
    # Word-wrap a string into <=ncols-char lines (cheap, for tiny screens).
    out = []
    line = ''
    for word in s.split(' '):
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= ncols:
            line += ' ' + word
        else:
            out.append(line); line = word
        while len(line) > ncols:        # a single long word
            out.append(line[:ncols]); line = line[ncols:]
    if line:
        out.append(line)
    return out or ['']


class Menu(Screen):
    """Classic vertical list — kept as a fallback home + used for sub-menus."""
    def __init__(self, title, items):
        self.title = title
        self.items = items            # list of (label, factory_or_None)
        self.sel = 0
        self.top = 0

    def _rows(self, c):
        return (c.h - _TOP) // _ROWH

    def draw(self, c):
        rows = self._rows(c)
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
                if fac is not None:
                    c.text(c.w - _ADV - 2, y, '>', 0)
            else:
                c.text(4, y, label, 1)
                if fac is None:
                    c.text(c.w - _ADV - 2, y, 'x', 1)

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


class Shelf(Screen):
    """Animated horizontal carousel — the home screen. Cards slide smoothly when
    you rotate; the centered card is highlighted. Slide duration is wall-clock
    constant (eased by dt), so it stays consistent at any framerate (and snaps if
    the loop is slow). Renders the same (label, factory) item list as Menu."""
    PITCH = 92          # px between card centers
    CW = 78             # card width
    SLIDE_MS = 140      # time for a one-step slide

    def __init__(self, title, items):
        self.title = title
        self.items = items
        self.sel = 0
        self.sel_f = 0.0

    def animating(self):
        return abs(self.sel_f - self.sel) > 0.01

    def tick(self, dt_ms=0):
        if not self.animating():
            if self.sel_f != self.sel:
                self.sel_f = float(self.sel)
                return True
            return False
        # move sel_f toward sel at PITCH/SLIDE_MS, framerate-independent
        step = (dt_ms or 16) / float(self.SLIDE_MS)
        d = self.sel - self.sel_f
        if abs(d) <= step:
            self.sel_f = float(self.sel)
        else:
            self.sel_f += step if d > 0 else -step
        return True

    def _card(self, c, cx, label, selected):
        cw = self.CW
        x = int(cx - cw // 2)
        top = _TOP + 1
        ch = c.h - top - 1
        if x + cw < 0 or x > c.w:
            return
        if selected:
            c.fill_rect(x, top, cw, ch, 1)        # solid highlight
            c.rect(x, top, cw, ch, 0)
            tc = 0
        else:
            c.rect(x, top, cw, ch, 1)
            tc = 1
        lines = _wrap(label, (cw - 6) // _ADV)[:2]
        ty = top + (ch - len(lines) * _ROWH) // 2
        for ln in lines:
            tw = len(ln) * _ADV
            c.text(x + (cw - tw) // 2, ty, ln, tc)
            ty += _ROWH

    def draw(self, c):
        cx0 = c.w // 2
        n = len(self.items)
        for i in range(n):
            cx = cx0 + (i - self.sel_f) * self.PITCH
            if cx < -self.CW or cx > c.w + self.CW:
                continue
            self._card(c, cx, self.items[i][0], i == self.sel)
        # chevrons + position
        if self.sel > 0:
            c.text(0, c.h // 2, '<', 1)
        if self.sel < n - 1:
            c.text(c.w - _ADV, c.h // 2, '>', 1)
        pos = '{}/{}'.format(self.sel + 1, n)
        c.text(c.w - len(pos) * _ADV - 1, c.h - _FH, pos, 1)

    def on_event(self, e):
        if e == ev.ROT_CW:
            if self.sel < len(self.items) - 1:
                self.sel += 1
        elif e == ev.ROT_CCW:
            if self.sel > 0:
                self.sel -= 1
        elif e == ev.SELECT:
            fac = self.items[self.sel][1]
            return fac() if fac else None
        elif e == ev.BACK:
            return 'back'
        return None


class TextScreen(Screen):
    """Scrollable read-only lines (status dumps, help)."""
    def __init__(self, title, lines):
        self.title = title
        self.lines = lines
        self.top = 0

    def _rows(self, c):
        return (c.h - _TOP) // _ROWH

    def draw(self, c):
        rows = self._rows(c)
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.lines):
                break
            c.text(2, _TOP + i * _ROWH, self.lines[idx][:21], 1)

    def on_event(self, e):
        rows = 4
        if e == ev.ROT_CW:
            if self.top + rows < len(self.lines):
                self.top += 1
        elif e == ev.ROT_CCW:
            if self.top > 0:
                self.top -= 1
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class RunningScreen(Screen):
    """A long action with a progress bar — BACK cancels (cancel-anything)."""
    def __init__(self, title, total=100):
        self.title = title
        self.total = total
        self.progress = 0
        self.cancelled = False
        self.done = False

    def draw(self, c):
        c.text(4, _TOP + 2, self.title[:20], 1)
        if self.done:
            c.text(4, _TOP + 14, 'Cancelled.' if self.cancelled else 'Done.', 1)
        else:
            bx, by, bw = 6, _TOP + 16, c.w - 12
            c.rect(bx, by, bw, 8, 1)
            fw = (self.progress * (bw - 2)) // max(1, self.total)
            c.fill_rect(bx + 1, by + 1, fw, 6, 1)
            c.text(4, by + 12, '{}%'.format((self.progress * 100) // max(1, self.total)), 1)
        c.text(4, c.h - _FH, 'BACK = cancel' if not self.done else 'BACK = exit', 1)

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
                return None
            return 'back'
        if e == ev.HOME:
            return 'home'
        return None


class ModuleTestScreen(Screen):
    """Runs a module's test (novamods) and shows the result lines. OK re-tests."""
    def __init__(self, key, label):
        self.title = label
        self.key = key
        self.lines = ['OK = run test']
        self.ok = None
        self._pending = False

    def draw(self, c):
        y = _TOP
        for ln in self.lines[:4]:
            c.text(4, y, ln[:21], 1)
            y += _ROWH
        tag = '' if self.ok is None else ('  [OK]' if self.ok else '  [--]')
        c.text(4, c.h - _FH, 'OK=test BACK=exit' + tag, 1)

    def tick(self, dt_ms=0):
        if self._pending:
            self._pending = False
            import novamods
            self.ok, self.lines = novamods.run_test(self.key)
            return True
        return False

    def on_event(self, e):
        if e == ev.SELECT or e == ev.ACTION:
            self.lines = ['Testing ' + self.title + '...']
            self.ok = None
            self._pending = True       # run in tick() so this frame paints first
            return None
        if e == ev.BACK:
            return 'back'
        if e == ev.HOME:
            return 'home'
        return None


class WiFiScreen(Screen):
    """Functional WiFi app: show status, scan, connect to a saved network."""
    def __init__(self):
        self.title = 'WiFi'
        self.nets = []          # list of (ssid, rssi, saved)
        self.sel = 0
        self.top = 0
        self.msg = 'OK = scan'
        self._pending = None    # 'scan' | ('connect', ssid)

    def _status_line(self):
        try:
            import net
            st = net.status()
            if st.get('connected'):
                return 'Online: ' + str(st.get('ssid', '?'))[:13]
            return 'Offline'
        except Exception:
            return 'net n/a'

    def draw(self, c):
        c.text(2, _TOP, self._status_line()[:21], 1)
        if self.nets:
            rows = (c.h - _TOP - _ROWH) // _ROWH
            if self.sel < self.top:
                self.top = self.sel
            elif self.sel >= self.top + rows:
                self.top = self.sel - rows + 1
            for i in range(rows):
                idx = self.top + i
                if idx >= len(self.nets):
                    break
                ssid, rssi, saved = self.nets[idx]
                y = _TOP + _ROWH + i * _ROWH
                mark = '*' if saved else ' '
                row = '{}{}'.format(mark, ssid[:16])
                if idx == self.sel:
                    c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                    c.text(2, y, row, 0)
                else:
                    c.text(2, y, row, 1)
        else:
            c.text(2, _TOP + _ROWH, self.msg[:21], 1)
            c.text(2, c.h - _FH, 'OK=scan BACK=exit', 1)

    def tick(self, dt_ms=0):
        if self._pending == 'scan':
            self._pending = None
            self._do_scan()
            return True
        if isinstance(self._pending, tuple) and self._pending[0] == 'connect':
            ssid = self._pending[1]
            self._pending = None
            self._do_connect(ssid)
            return True
        return False

    def _do_scan(self):
        try:
            import net
            saved = []
            try:
                saved = [s for s, _p in net._read_networks()]
            except Exception:
                pass
            sl = {s.lower() for s in saved}
            res = net.scan() or []
            nets = []
            for r in res:
                try:
                    ssid = r[0].decode() if isinstance(r[0], (bytes, bytearray)) else str(r[0])
                    rssi = r[3] if len(r) > 3 else 0
                except Exception:
                    continue
                if ssid:
                    nets.append((ssid, rssi, ssid.lower() in sl))
            nets.sort(key=lambda x: x[1], reverse=True)
            self.nets = nets[:20]
            self.sel = self.top = 0
            self.msg = 'No networks' if not nets else ''
        except Exception as e:
            self.msg = 'scan err: ' + str(e)[:12]

    def _do_connect(self, ssid):
        try:
            import net
            ok = False
            try:
                ok = net.connect_saved(ssid)
            except TypeError:
                ok = net.connect_saved()
            self.msg = ('Connected ' if ok else 'No saved pw: ') + ssid[:10]
        except Exception as e:
            self.msg = 'conn err: ' + str(e)[:12]
        self.nets = []          # back to the status view

    def on_event(self, e):
        if not self.nets:
            if e == ev.SELECT:
                self.msg = 'Scanning...'
                self._pending = 'scan'
                return None
            if e in (ev.BACK, ev.HOME):
                return e
            return None
        if e == ev.ROT_CW:
            self.sel = min(self.sel + 1, len(self.nets) - 1)
        elif e == ev.ROT_CCW:
            self.sel = max(self.sel - 1, 0)
        elif e == ev.SELECT:
            ssid, _r, saved = self.nets[self.sel]
            if saved:
                self.msg = 'Connecting...'
                self._pending = ('connect', ssid)
            else:
                self.msg = 'Not saved (use shell)'
                self.nets = []
            return None
        elif e == ev.BACK:
            self.nets = []       # back to status, not out of the app
            return None
        elif e == ev.HOME:
            return 'home'
        return None


class ManageAppsScreen(Menu):
    """Toggle which apps show on the home shelf (persisted to the registry)."""
    def __init__(self, all_apps, enabled):
        self._all = all_apps                 # list of (key, label)
        self._on = set(enabled)
        items = [(self._row(k, l), None) for k, l in all_apps]
        Menu.__init__(self, 'Manage Apps', items)

    def _row(self, key, label):
        return ('[x] ' if key in self._on else '[ ] ') + label

    def on_event(self, e):
        if e == ev.SELECT:
            key, label = self._all[self.sel]
            if key in self._on:
                if len(self._on) > 1:
                    self._on.discard(key)
            else:
                self._on.add(key)
            self.items[self.sel] = (self._row(key, label), None)
            order = [k for k, _l in self._all if k in self._on]
            _save_reg('Apps.NovaD1_Home', ','.join(order))
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


# --- the runner -------------------------------------------------------------
class NovaUI:
    def __init__(self, display, canvas, source, state_provider, home):
        self.display = display
        self.canvas = canvas
        self.source = source
        self.state = state_provider
        self.stack = [home]
        self._stop = False
        self._state_cache = None
        self._state_t = -100000
        self._last_render = 0

    def _now(self):
        try:
            import utime
            return utime.ticks_ms()
        except Exception:
            import time
            return int(time.time() * 1000)

    def _get_state(self, now):
        # Refresh the (possibly slow) status provider at most ~once a second.
        if self._state_cache is None or (now - self._state_t) >= 1000:
            st = self.state() if callable(self.state) else dict(self.state)
            self._state_cache = st
            self._state_t = now
        return dict(self._state_cache)

    def render(self, now=None):
        if now is None:
            now = self._now()
        c = self.canvas
        c.clear(0)
        st = self._get_state(now)
        st['title'] = self.stack[-1].title
        draw_status_bar(c, st)
        self.stack[-1].draw(c)
        self.display.show(c)
        self._last_render = now

    def handle(self, e):
        if e is None:
            return False
        r = self.stack[-1].on_event(e)
        if r == 'back':
            if len(self.stack) > 1:
                self.stack.pop()
        elif r == 'home':
            del self.stack[1:]
        elif isinstance(r, Screen):
            self.stack.append(r)
        return True

    def _loop_once(self, prev, sleep_ms):
        now = self._now()
        dt = now - prev
        dirty = False
        e = self.source.poll()
        if e is not None:
            dirty = self.handle(e) or dirty
        scr = self.stack[-1]
        if scr.tick(dt):
            dirty = True
        if (now - self._last_render) >= 1000:    # keep the clock/signal live
            dirty = True
        if dirty:
            self.render(now)
        # pace: fast frames while animating, relaxed when idle
        nap = 16 if scr.animating() else sleep_ms
        return now, nap

    def run(self, sleep_ms=40):
        try:
            import utime as _t
            _sleep = _t.sleep_ms
        except ImportError:
            import time as _tt
            def _sleep(ms): _tt.sleep(ms / 1000.0)
        self._stop = False
        self.render()
        prev = self._now()
        while not self._stop:
            prev, nap = self._loop_once(prev, sleep_ms)
            _sleep(nap)

    async def run_async(self, sleep_ms=40):
        # Cooperative loop — runs as a BACKGROUND SERVICE so the serial shell
        # stays free (OLED and shell are separate surfaces). Yields every tick.
        import asyncio
        self._stop = False
        self.render()
        prev = self._now()
        while not self._stop:
            prev, nap = self._loop_once(prev, sleep_ms)
            await asyncio.sleep_ms(nap)

    def stop(self):
        self._stop = True


# --- home screen — built from the module registry + homepage config ----------
def _mk_test(key, label):
    return lambda: ModuleTestScreen(key, label)


def _all_apps():
    """Every possible home app: (key, label, factory). Modules + built-in apps."""
    import novamods
    apps = [(k, l, _mk_test(k, l)) for k, l, _fn in novamods.MODULES]
    apps.append(('wifi', 'WiFi', WiFiScreen))
    apps.append(('scripts', 'Scripts',
                 lambda: Menu('Scripts', [('hello.rps', None), ('blink.py', None)])))
    return apps


def _home_keys():
    """Enabled home apps in order. Registry csv 'Apps.NovaD1_Home'; default all."""
    raw = _reg('Apps.NovaD1_Home')
    if not raw:
        return None
    keys = [k.strip() for k in raw.split(',') if k.strip()]
    return keys or None


def build_home(modules=None, use_shelf=True):
    """Home = a card per enabled app + Settings. `modules` (key->present) greys
    out auto-undetected ones; homepage config (Apps.NovaD1_Home) picks/orders."""
    modules = modules or {}
    apps = _all_apps()
    enabled = _home_keys()
    if enabled is not None:
        order = {k: i for i, k in enumerate(enabled)}
        apps = sorted([a for a in apps if a[0] in order], key=lambda a: order[a[0]])
    items = []
    for key, label, fac in apps:
        present = modules.get(key, True)
        items.append((label, fac if present else None))

    def _settings():
        all_for_cfg = [(k, l) for k, l, _f2 in _all_apps()]
        cur = _home_keys() or [k for k, _l in all_for_cfg]
        return Menu('Settings', [
            ('Manage Apps', lambda: ManageAppsScreen(all_for_cfg, cur)),
            ('Display', None),
            ('Time', None),
        ])
    items.append(('Settings', _settings))
    if use_shelf:
        return Shelf('Nova D1', items)
    return Menu('Nova D1', items)
