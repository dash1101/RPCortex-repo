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
import novaicons
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


class IconGallery(Screen):
    """Animated icon gallery — the home screen. Small neighbour icons on the
    sides, a bigger highlighted one in the centre, the app name underneath. Icons
    slide + grow/shrink smoothly when you rotate; the slide is wall-clock constant
    (eased by dt) so it's consistent at any framerate and snaps if the loop is
    slow. Items are (key, label, factory) triples (key drives the icon)."""
    PITCH = 42          # px between icon centres
    RBIG = 13           # centred icon half-size
    RSML = 6            # neighbour icon half-size
    SLIDE_MS = 130

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
        step = (dt_ms or 16) / float(self.SLIDE_MS)
        d = self.sel - self.sel_f
        if abs(d) <= step:
            self.sel_f = float(self.sel)
        else:
            self.sel_f += step if d > 0 else -step
        return True

    def draw(self, c):
        cx0 = c.w // 2
        icy = _TOP + (c.h - _TOP) // 2 - 3
        n = len(self.items)
        # draw neighbours first, centre last (so the big one overlaps cleanly)
        order = sorted(range(n), key=lambda i: -abs(i - self.sel_f))
        for i in order:
            off = i - self.sel_f
            if abs(off) > 1.7:
                continue
            cx = int(cx0 + off * self.PITCH)
            r = int(self.RSML + (self.RBIG - self.RSML) * max(0.0, 1.0 - abs(off)))
            key, label = self.items[i][0], self.items[i][1]
            novaicons.draw(c, key, cx, icy, r, label)
        # name of the centred app
        lbl = self.items[self.sel][1]
        maxc = c.w // _ADV
        lbl = lbl[:maxc]
        c.text((c.w - len(lbl) * _ADV) // 2, c.h - _FH, lbl, 1)
        # position + edge chevrons
        pos = '{}/{}'.format(self.sel + 1, n)
        c.text(c.w - len(pos) * _ADV, _TOP - 1, pos, 1)
        if self.sel > 0:
            c.text(0, icy - _FH // 2, '<', 1)
        if self.sel < n - 1:
            c.text(c.w - _ADV, icy - _FH // 2, '>', 1)

    def on_event(self, e):
        if e == ev.ROT_CW:
            if self.sel < len(self.items) - 1:
                self.sel += 1
        elif e == ev.ROT_CCW:
            if self.sel > 0:
                self.sel -= 1
        elif e == ev.SELECT:
            fac = self.items[self.sel][2]
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
    """Runs a module's test cooperatively (novamods generator). Progress updates
    live; BACK cancels instantly (closes the generator -> the test's `finally`
    frees the hardware). Select runs/re-runs."""
    def __init__(self, key, label):
        self.title = label
        self.key = key
        self.lines = ['Select = run', 'BACK = exit']
        self.ok = None
        self._gen = None
        self._cancel = False
        self.top = 0

    def _running(self):
        return self._gen is not None

    def _wrapped(self, c):
        cols = (c.w - 3) // _ADV
        out = []
        for ln in self.lines:
            out.extend(_wrap(ln, cols))
        return out

    def draw(self, c):
        wl = self._wrapped(c)
        rows = (c.h - _TOP - _FH) // _ROWH
        if self._running():
            self.top = 0                       # pin to top so progress doesn't fight scroll
        if self.top > max(0, len(wl) - rows):
            self.top = max(0, len(wl) - rows)
        for i in range(rows):
            idx = self.top + i
            if idx >= len(wl):
                break
            c.text(2, _TOP + i * _ROWH, wl[idx], 1)
        if len(wl) > rows and not self._running():
            c.text(c.w - _ADV, _TOP, '^' if self.top else 'v', 1)
        if self._running():
            foot = 'BACK = stop'
        else:
            tag = '' if self.ok is None else (' [OK]' if self.ok else ' [X]')
            foot = 'Select=run' + tag
        c.text(2, c.h - _FH, foot[:16], 1)

    def _stop_gen(self):
        self._cancel = True
        if self._gen is not None:
            try:
                self._gen.close()
            except Exception:
                pass
            self._gen = None

    def tick(self, dt_ms=0):
        if self._gen is None:
            return False
        try:
            status, lines = next(self._gen)
            self.lines = lines
            if status is not None:
                self.ok = status
                self._gen = None
            return True
        except StopIteration:
            self._gen = None
            return True
        except Exception as e:
            self.lines = [self.title, 'error', str(e)[:16]]
            self.ok = False
            self._gen = None
            return True

    def on_event(self, e):
        if e == ev.ROT_CW and not self._running():
            self.top += 1
            return None
        if e == ev.ROT_CCW and not self._running():
            self.top = max(0, self.top - 1)
            return None
        if e == ev.SELECT:
            if self._gen is None:
                import novamods
                self._cancel = False
                self.ok = None
                self.top = 0
                self.lines = ['Testing...']
                self._gen = novamods.run_test(self.key, lambda: self._cancel)
            return None
        if e == ev.BACK:
            if self._running():
                self._stop_gen()
                self.lines = [self.title, 'Cancelled']
                self.ok = False
                return None                 # stay; BACK again exits
            return 'back'
        if e == ev.HOME:
            self._stop_gen()
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


class SplashScreen(Screen):
    """Animated RPCortex / Nova D1 boot reveal. Auto-advances; any key skips."""
    fullscreen = True
    DUR = 1500

    def __init__(self):
        self.title = 'Nova D1'
        self.t = 0.0
        self.next = None

    def draw(self, c):
        import novasplash
        novasplash.draw(c, self.t if self.t < 1 else 1.0)

    def tick(self, dt_ms=0):
        if self.t >= 1.0:
            self.next = 'back'
            return False
        self.t += (dt_ms or 16) / float(self.DUR)
        return True

    def on_event(self, e):
        self.next = 'back'                 # any key skips the splash
        return None


class BootCheckScreen(Screen):
    """Loading-bar module check after the splash. Auto-advances when done."""
    fullscreen = True

    def __init__(self):
        self.title = 'Checks'
        self.next = None
        self._gen = None
        self._started = False
        self.results = []
        self.done = 0
        self.total = 1
        self._hold = 0
        self._cancel = False

    def draw(self, c):
        w = c.w
        t = 'System Check'
        c.text((w - len(t) * _ADV) // 2, 1, t, 1)
        bx, by, bw = 6, 14, w - 12
        c.rect(bx, by, bw, 9, 1)
        frac = self.done / float(self.total) if self.total else 0
        c.fill_rect(bx + 1, by + 1, int((bw - 2) * frac), 7, 1)
        y = 28
        for label, st in self.results[-3:]:
            mark = 'OK' if st == 'ok' else ('--' if st == '--' else 'na')
            c.text(4, y, label[:11], 1)
            c.text(w - 2 * _ADV - 2, y, mark, 1)
            y += _ROWH

    def tick(self, dt_ms=0):
        if not self._started:
            self._started = True
            import novamods
            self._gen = novamods.quickcheck(lambda: self._cancel)
            return True
        if self._gen is None:
            self._hold += dt_ms or 16
            if self._hold > 700:
                self.next = 'back'
            return False
        try:
            i, total, label, st, results = next(self._gen)
            self.done = i; self.total = total; self.results = results
            return True
        except StopIteration:
            self._gen = None
            try:
                import novalog
                ok = sum(1 for _l, s in self.results if s == 'ok')
                novalog.log('boot check: {}/{} present'.format(ok, len(self.results)))
            except Exception:
                pass
            return True
        except Exception:
            self._gen = None
            return True

    def on_event(self, e):
        self._cancel = True
        self.next = 'back'                 # any key skips
        return None


class SystemCheckScreen(Screen):
    """On-demand module check (same probes), scrollable, Select re-runs."""
    def __init__(self):
        self.title = 'Sys Check'
        self.results = []
        self.top = 0
        self._gen = None
        self._cancel = False
        self.done = 0
        self.total = 1
        self._auto = True                  # run once on open

    def _start(self):
        import novamods
        self._cancel = False
        self.results = []
        self.top = 0
        self._gen = novamods.quickcheck(lambda: self._cancel)

    def draw(self, c):
        if self._gen is not None:
            bx, by, bw = 6, _TOP, c.w - 12
            c.rect(bx, by, bw, 9, 1)
            frac = self.done / float(self.total) if self.total else 0
            c.fill_rect(bx + 1, by + 1, int((bw - 2) * frac), 7, 1)
            c.text(2, by + 12, 'checking...', 1)
            return
        rows = (c.h - _TOP - _FH) // _ROWH
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.results):
                break
            label, st = self.results[idx]
            mark = 'OK' if st == 'ok' else ('--' if st == '--' else 'na')
            c.text(2, _TOP + i * _ROWH, label[:11], 1)
            c.text(c.w - 2 * _ADV - 2, _TOP + i * _ROWH, mark, 1)
        c.text(2, c.h - _FH, 'Select=rerun', 1)

    def tick(self, dt_ms=0):
        if self._auto:
            self._auto = False
            self._start()
            return True
        if self._gen is None:
            return False
        try:
            i, total, label, st, results = next(self._gen)
            self.done = i; self.total = total; self.results = results
            return True
        except StopIteration:
            self._gen = None
            try:
                import novalog
                ok = sum(1 for _l, s in self.results if s == 'ok')
                novalog.log('sys check: {}/{} present'.format(ok, len(self.results)))
            except Exception:
                pass
            return True
        except Exception:
            self._gen = None
            return True

    def on_event(self, e):
        if e == ev.SELECT and self._gen is None:
            self._start()
            return None
        if e == ev.ROT_CW and self._gen is None:
            self.top += 1
            return None
        if e == ev.ROT_CCW and self._gen is None:
            self.top = max(0, self.top - 1)
            return None
        if e == ev.BACK:
            self._cancel = True
            return 'back'
        if e == ev.HOME:
            self._cancel = True
            return 'home'
        return None


class ErrorScreen(Screen):
    """Shown on startup after the GUI recovered from a crash. Any key dismisses."""
    def __init__(self, msg):
        self.title = 'Recovered'
        self.lines = _wrap('Crashed: ' + str(msg), 16)[:4]

    def draw(self, c):
        y = _TOP
        for ln in self.lines:
            c.text(2, y, ln[:16], 1)
            y += _ROWH
        c.text(2, c.h - _FH, 'any key = ok', 1)

    def on_event(self, e):
        return 'back'                      # any event pops back to home


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
        scr = self.stack[-1]
        if not getattr(scr, 'fullscreen', False):
            st = self._get_state(now)
            st['title'] = scr.title
            draw_status_bar(c, st)
        scr.draw(c)
        self.display.show(c)
        self._last_render = now

    def _apply(self, r):
        if r == 'back':
            if len(self.stack) > 1:
                self.stack.pop()
        elif r == 'home':
            del self.stack[1:]
        elif isinstance(r, Screen):
            self.stack.append(r)

    def handle(self, e):
        if e is None:
            return False
        self._apply(self.stack[-1].on_event(e))
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
        nx = getattr(scr, 'next', None)          # a screen can auto-advance itself
        if nx is not None:
            scr.next = None
            self._apply(nx)
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


def _logs_screen():
    try:
        import novalog
        lines = novalog.tail(40)
    except Exception:
        lines = []
    return TextScreen('Nova Logs', lines or ['(no log yet)'])


def _scripts_screen():
    # Lists scripts from the Nova store (SD if mounted, else flash). Running them
    # comes with the scripting feature; for now it's a browsable list.
    try:
        import novad1
        path = novad1.scripts_dir()
        import uos
        files = [f for f in uos.listdir(path)]
    except Exception:
        files = []
    items = [(f, None) for f in files] or [('(no scripts)', None)]
    return Menu('Scripts', items)


def _all_apps():
    """Every possible home app: (key, label, factory). Modules + built-in apps."""
    import novamods
    apps = [(k, l, _mk_test(k, l)) for k, l, _fn in novamods.MODULES]
    apps.append(('wifi', 'WiFi', WiFiScreen))
    apps.append(('check', 'Sys Check', SystemCheckScreen))
    apps.append(('logs', 'Logs', _logs_screen))
    apps.append(('scripts', 'Scripts', _scripts_screen))
    return apps


def make_boot_stack(home):
    """Boot order: home at the bottom, then the check, then the splash on top —
    splash plays -> pops to check -> check runs -> pops to home."""
    return [home, BootCheckScreen(), SplashScreen()]


def _home_keys():
    """Enabled home apps in order. Registry csv 'Apps.NovaD1_Home'; default all."""
    raw = _reg('Apps.NovaD1_Home')
    if not raw:
        return None
    keys = [k.strip() for k in raw.split(',') if k.strip()]
    return keys or None


def _settings_menu():
    all_for_cfg = [(k, l) for k, l, _f2 in _all_apps()]
    cur = _home_keys() or [k for k, _l in all_for_cfg]
    return Menu('Settings', [
        ('Manage Apps', lambda: ManageAppsScreen(all_for_cfg, cur)),
        ('Display', None),
        ('Time', None),
    ])


def build_home(modules=None, style=None):
    """Home = an icon per enabled app + Settings. `modules` (key->present) greys
    out auto-undetected ones; homepage config (Apps.NovaD1_Home) picks/orders;
    Apps.NovaD1_HomeStyle = 'gallery' (default) | 'menu' picks the layout."""
    modules = modules or {}
    apps = _all_apps()                       # (key, label, factory) triples
    enabled = _home_keys()
    if enabled is not None:
        order = {k: i for i, k in enumerate(enabled)}
        apps = sorted([a for a in apps if a[0] in order], key=lambda a: order[a[0]])
    triples = []
    for key, label, fac in apps:
        present = modules.get(key, True)
        triples.append((key, label, fac if present else None))
    triples.append(('settings', 'Settings', _settings_menu))
    if style is None:
        style = _reg('Apps.NovaD1_HomeStyle', 'gallery')
    if style == 'menu':
        return Menu('Nova D1', [(l, f) for _k, l, f in triples])
    return IconGallery('Nova D1', triples)
