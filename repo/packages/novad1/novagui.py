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


def _int_reg(key, default=0):
    try:
        return int(_reg(key, default) or 0)
    except (TypeError, ValueError):
        return default


# The running UI, so screens (Display/Time) can reach the live display/hardware.
_active_ui = None
# Set when the home app list/style changes so the runner rebuilds the home live
# (no reboot needed — was the "apps don't remove until reboot" bug).
_home_dirty = False


def _mark_home_dirty():
    global _home_dirty
    _home_dirty = True


def _disp():
    return _active_ui.display if _active_ui is not None else None


def perf_stats():
    ui = _active_ui
    if ui is None:
        return None
    try:
        idle_s = (ui._now() - ui._idle_t0) // 1000
    except Exception:
        idle_s = -1
    d = {'render_us': ui._render_us, 'render_max_us': ui._render_max,
         'shows': ui._shows, 'dimmed': ui._dimmed,
         # screen-timeout diagnostics: discriminate idle-never-crosses vs
         # contrast-not-dark vs a stale/0 timer setting shadowing the default.
         'level': ui._level, 'idle_s': idle_s,
         'dim_s': _int_reg('Apps.NovaD1_DimSec', 15),
         'off_s': _int_reg('Apps.NovaD1_OffSec', 60),
         'lock_s': _int_reg('Apps.NovaD1_LockSec', 5)}
    ui._render_max = 0                           # reset the peak each read
    return d


def _apply_invert(val):
    d = _disp()
    if d is not None:
        try:
            d.invert(val == 'on')
        except Exception:
            pass


def _apply_web(val):
    try:
        import novad1
        novad1.set_web(val == 'on')
    except Exception:
        pass


# --- status-bar icons (primitives — no bitmap blobs to maintain) ------------
def _wifi(c, x, y, st):
    # st: 'connected' (3 bars) / 'connecting' (1 bar) / 'off' (baseline dots).
    if st is True:
        st = 'connected'
    elif st is False or st is None:
        st = 'off'
    n = 3 if st == 'connected' else (1 if st == 'connecting' else 0)
    for i in range(3):
        bx = x + i * 3
        h = 2 + i * 2
        if i < n:
            c.fill_rect(bx, y + (6 - h), 2, h, 1)
        else:
            c.pixel(bx, y + 5, 1); c.pixel(bx + 1, y + 5, 1)


def _battery(c, x, y, pct, low=False):
    c.rect(x, y, 11, 6, 1)
    c.fill_rect(x + 11, y + 2, 1, 2, 1)         # nub
    if low:
        c.pixel(x + 5, y + 2, 1)                # '!' when low (rest empty)
        c.pixel(x + 5, y + 4, 1)
        return
    fillw = (pct * 9) // 100
    if fillw > 0:
        c.fill_rect(x + 1, y + 1, fillw, 4, 1)


def _usb(c, x, y):
    # small USB plug glyph (~7 wide)
    c.hline(x, y + 2, 6, 1)
    c.fill_rect(x, y + 1, 2, 3, 1)
    c.pixel(x + 3, y, 1)
    c.pixel(x + 5, y + 4, 1)
    c.pixel(x + 6, y + 2, 1)


def _bell(c, x, y):
    # small bell glyph (~6 wide) — shown when there are unread notifications
    c.hline(x + 1, y, 3, 1)
    c.line(x, y + 4, x + 1, y + 1, 1)
    c.line(x + 4, y + 1, x + 5, y + 4, 1)
    c.hline(x - 1, y + 4, 7, 1)
    c.pixel(x + 2, y + 5, 1)


def _disk(c, x, y):
    # small floppy/save glyph (~7 wide) — shown while a code is backing up to SD
    c.rect(x, y, 7, 7, 1)
    c.fill_rect(x + 2, y, 3, 2, 1)              # notch
    c.fill_rect(x + 1, y + 4, 5, 3, 1)          # label


def draw_status_bar(c, state):
    # Right-aligned clock, then (battery)(usb)(wifi) leftward, then title fills the
    # rest — all measured from _ADV so a font swap can't clip the clock. Battery +
    # USB icons appear ONLY when power info says they're present (no lying icon).
    w = c.w
    tstr = state.get('time', '--:--')
    tx = w - len(tstr) * _ADV
    c.text(tx, 1, tstr, 1)
    x = tx - 3
    pwr = state.get('power') or {}
    if pwr.get('have'):
        x -= 12
        _battery(c, x, 2, pwr.get('pct', 0), pwr.get('low'))
        x -= 3
    if pwr.get('usb'):
        x -= 7
        _usb(c, x, 1)
        x -= 3
    x -= 8
    _wifi(c, x, 2, state.get('wifi', False))
    if state.get('saving'):                 # SD backup in progress -> save icon
        x -= 9
        _disk(c, x, 1)
    if state.get('notify'):                 # unread notifications -> bell
        x -= 9
        _bell(c, x, 1)
    title = state.get('title', 'Nova D1')
    maxc = max(1, (x - 4) // _ADV)
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


def _scroll_tri(c, x, y, up):
    """A tiny 5px up/down triangle — a 'more above/below' scroll hint for lists."""
    if up:
        c.hline(x + 2, y, 1)
        c.hline(x + 1, y + 1, 3)
        c.hline(x, y + 2, 5)
    else:
        c.hline(x, y, 5)
        c.hline(x + 1, y + 1, 3)
        c.hline(x + 2, y + 2, 1)


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
            label = label[:(c.w - 14) // _ADV]      # truncate to fit (no overflow)
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
        if self.top > 0:
            _scroll_tri(c, c.w - 6, _TOP, True)          # more items above
        if self.top + rows < len(self.items):
            _scroll_tri(c, c.w - 6, c.h - 4, False)      # more items below

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
        n = len(self.items)
        if e == ev.ROT_CW:
            if self.sel == n - 1:               # wrap end -> start: slide the new
                self.sel = 0; self.sel_f = -1.0 # item IN from the right (one step)
            else:
                self.sel += 1
        elif e == ev.ROT_CCW:
            if self.sel == 0:                   # wrap start -> end: slide IN from left
                self.sel = n - 1; self.sel_f = float(n)
            else:
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
            c.text(2, _TOP + i * _ROWH, self.lines[idx][:16], 1)

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
        c.text(4, _TOP + 2, self.title[:16], 1)
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
                return 'Online: ' + str(st.get('ssid', '?'))[:7]
            return 'Offline'
        except Exception:
            return 'net n/a'

    def draw(self, c):
        c.text(2, _TOP, self._status_line()[:16], 1)
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
            c.text(2, _TOP + _ROWH, self.msg[:16], 1)
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
        # Scan via the STA interface directly, pausing the background WiFi manager
        # so it isn't mid-connect on the same interface (that broke scan in 0.8.0).
        import novawifi
        novawifi.pause()
        try:
            import network
            saved = []
            try:
                import net
                saved = [s for s, _p in net._read_networks()]
            except Exception:
                pass
            sl = set(s.lower() for s in saved)
            wlan = network.WLAN(network.STA_IF)
            if not wlan.active():
                wlan.active(True)
            res = wlan.scan() or []
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
        finally:
            novawifi.resume()

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


class ManageAppsScreen(Screen):
    """Manage the home apps. Not grabbed: SELECT toggles an app on/off. HOME grabs the
    app to EDIT it — then turn to reorder, SELECT cycles which folder it lives in
    (Wireless/Sensors/Tools/System, or back to its default), HOME drops it. Order +
    enabled set persist to Apps.NovaD1_Home; folder reassignments to Apps.NovaD1_AppCats."""
    def __init__(self, all_apps, enabled):
        self.title = 'Manage Apps'
        self._label = {}
        keys = []
        for k, l in all_apps:
            self._label[k] = l
            keys.append(k)
        self._on = set(enabled) or set(keys)
        # order: enabled apps first (in their saved order), then the rest.
        order = [k for k in enabled if k in self._label]
        self._order = order + [k for k in keys if k not in order]
        self.sel = 0
        self.top = 0
        self._moving = False

    def _save(self):
        _save_reg('Apps.NovaD1_Home', ','.join(k for k in self._order if k in self._on))
        _mark_home_dirty()

    def draw(self, c):
        rows = max(1, (c.h - _TOP - _FH) // _ROWH)   # reserve a footer line
        n = len(self._order)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= n:
                break
            k = self._order[idx]
            y = _TOP + i * _ROWH
            mark = '[x] ' if k in self._on else '[ ] '
            label = (mark + self._label.get(k, k))[:(c.w - 10) // _ADV]
            if idx == self.sel:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                c.text(4, y, label, 0)
                c.text(c.w - _ADV - 2, y, '=' if self._moving else '>', 0)
            else:
                c.text(4, y, label, 1)
        body_bot = _TOP + rows * _ROWH
        if self.top > 0:
            _scroll_tri(c, c.w - 6, _TOP, True)
        if self.top + rows < n:
            _scroll_tri(c, c.w - 6, body_bot - 4, False)
        # footer: mode-aware controls (shows the app's folder while editing it)
        k = self._order[self.sel]
        foot = ('turn=move  SEL=' + _app_category(k)) if self._moving else 'SEL on/off  HOME edit'
        c.text(2, c.h - _FH, foot[:(c.w - 4) // _ADV], 1)

    def on_event(self, e):
        n = len(self._order)
        if e == ev.ROT_CW:
            if self._moving and self.sel < n - 1:
                self._order[self.sel], self._order[self.sel + 1] = \
                    self._order[self.sel + 1], self._order[self.sel]
                self.sel += 1
                self._save()
            else:
                self.sel = (self.sel + 1) % n
            return None
        if e == ev.ROT_CCW:
            if self._moving and self.sel > 0:
                self._order[self.sel], self._order[self.sel - 1] = \
                    self._order[self.sel - 1], self._order[self.sel]
                self.sel -= 1
                self._save()
            else:
                self.sel = (self.sel - 1) % n
            return None
        if e == ev.SELECT:
            k = self._order[self.sel]
            if self._moving:
                # grabbed => SELECT cycles the app's home folder; the last step (None)
                # clears the override, restoring its built-in/auto category.
                seq = list(_CATEGORIES) + [None]
                cur = _CAT_OVERRIDE.get(k)
                try:
                    i = seq.index(cur)
                except ValueError:
                    i = len(seq) - 1
                _set_cat_override(k, seq[(i + 1) % len(seq)])
            elif k in self._on:
                if len(self._on) > 1:
                    self._on.discard(k)
                    self._save()
            else:
                self._on.add(k)
                self._save()
            return None
        if e == ev.HOME:
            self._moving = not self._moving        # grab an app: turn=reorder, SELECT=folder
            return None
        if e == ev.BACK:
            if self._moving:
                self._moving = False
                return None
            return 'back'
        return None


class DisplayScreen(Screen):
    """Adjust OLED brightness as 0-100% (steps of 10), stored as 0-255 contrast."""
    def __init__(self):
        self.title = 'Display'
        try:
            raw = int(_reg('Apps.NovaD1_Contrast', 255))
        except Exception:
            raw = 255
        self.pct = max(0, min(100, round(raw * 100 / 255 / 10) * 10))

    def draw(self, c):
        c.text(2, _TOP, 'Brightness', 1)
        bx, by, bw = 6, _TOP + _ROWH, c.w - 12
        c.rect(bx, by, bw, 9, 1)
        c.fill_rect(bx + 1, by + 1, int((bw - 2) * self.pct / 100), 7, 1)
        c.text(2, by + 12, '{}%'.format(self.pct), 1)
        c.text(2, c.h - _FH, 'turn=adj BACK=save', 1)

    def _raw(self):
        return max(10, int(self.pct * 255 / 100))   # never fully 0 (keep visible)

    def _apply(self):
        d = _disp()
        if d is not None:
            try:
                d.contrast(self._raw())
            except Exception:
                pass

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.pct = min(100, self.pct + 10); self._apply()
        elif e == ev.ROT_CCW:
            self.pct = max(10, self.pct - 10); self._apply()
        elif e in (ev.BACK, ev.HOME):
            _save_reg('Apps.NovaD1_Contrast', str(self._raw()))
            return e
        return None


class TimeScreen(Screen):
    """Set the hardware clock (hour/minute). Select switches field, turn adjusts."""
    def __init__(self):
        self.title = 'Set Time'
        self.field = 0
        try:
            import utime
            t = utime.localtime()
            self.h, self.m = t[3], t[4]
        except Exception:
            self.h, self.m = 0, 0

    def draw(self, c):
        s = '{:02d}:{:02d}'.format(self.h, self.m)
        sc = 2
        tw = len(s) * _ADV * sc
        x = (c.w - tw) // 2
        y = _TOP + 4
        c.text(x, y, s, 1, sc)
        # underline the active field
        ux = x if self.field == 0 else x + 3 * _ADV * sc
        c.hline(ux, y + _FH * sc + 1, 2 * _ADV * sc, 1)
        c.text(2, c.h - _FH, 'Sel=field BACK=set', 1)

    def on_event(self, e):
        d = 1 if e == ev.ROT_CW else (-1 if e == ev.ROT_CCW else 0)
        if d:
            if self.field == 0:
                self.h = (self.h + d) % 24
            else:
                self.m = (self.m + d) % 60
            return None
        if e == ev.SELECT:
            self.field ^= 1
            return None
        if e in (ev.BACK, ev.HOME):
            try:
                import machine
                import utime
                t = utime.localtime()
                machine.RTC().datetime((t[0], t[1], t[2], t[6], self.h, self.m, 0, 0))
            except Exception:
                pass
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
            self._gen = novamods.quickcheck(lambda: self._cancel, fast=True)
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


class MessagesScreen(Screen):
    """LoRa messaging view — backed by the shared novamsg manager (same inbox the
    web panel uses). Shows the conversation; Select broadcasts a quick 'ping'.
    Compose real text from the web panel (phone keyboard). The manager owns the
    radio + listens in the background, so messages arrive even off this screen."""
    def __init__(self):
        self.title = 'Messages'
        self.top = 0
        self._last = -1

    def _lines(self):
        try:
            import novamsg
            box = novamsg.inbox()
        except Exception:
            box = []
        out = []
        for m in box:
            who = 'me' if m.get('me') else str(m.get('src', '?'))
            out.append('{}: {}'.format(who, m.get('text', '')))
        return out

    def draw(self, c):
        try:
            import novamsg
            ok = novamsg.radio_ok()
        except Exception:
            ok = False
        if not ok:
            c.text(2, _TOP, 'LoRa: no radio', 1)
            c.text(2, _TOP + _ROWH, 'check SX1276 wiring', 1)
            c.text(2, c.h - _FH, 'BACK = exit', 1)
            return
        lines = self._lines()
        rows = (c.h - _TOP - _FH) // _ROWH
        wl = []
        for ln in lines:
            wl.extend(_wrap(ln, (c.w - 3) // _ADV))
        if len(wl) > rows:                       # auto-stick to newest
            self.top = len(wl) - rows
        if not wl:
            c.text(2, _TOP, '(listening...)', 1)
        for i in range(rows):
            idx = self.top + i
            if 0 <= idx < len(wl):
                c.text(2, _TOP + i * _ROWH, wl[idx], 1)
        enc = ''
        try:
            import novacrypt
            if novacrypt.have_key():
                enc = ' *enc'
        except Exception:
            pass
        c.text(2, c.h - _FH, ('Sel=ping BACK=exit' + enc)[:16], 1)

    def tick(self, dt_ms=0):
        try:
            import novamsg
            n = len(novamsg.inbox())
        except Exception:
            n = 0
        if n != self._last:                      # redraw when the inbox changes
            self._last = n
            return True
        return False

    def on_event(self, e):
        if e == ev.SELECT:
            try:
                import novamsg
                import novamesh
                novamsg.send('ping ' + str(novamesh.node_id()))
            except Exception:
                pass
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


class NotificationsScreen(Screen):
    """View recent notifications (newest first); Select clears. Marks read on open."""
    def __init__(self):
        self.title = 'Notes'
        self.top = 0
        try:
            import novanotify
            novanotify.mark_read()
        except Exception:
            pass

    def _lines(self):
        try:
            import novanotify
            it = novanotify.items()
        except Exception:
            it = []
        out = []
        for ts, txt in reversed(it):
            out.append(ts + ' ' + txt)
        return out

    def draw(self, c):
        lines = self._lines()
        rows = (c.h - _TOP - _FH) // _ROWH
        if not lines:
            c.text(2, _TOP, '(no notifications)', 1)
        wl = []
        for ln in lines:
            wl.extend(_wrap(ln, (c.w - 3) // _ADV))
        if self.top > max(0, len(wl) - rows):
            self.top = max(0, len(wl) - rows)
        for i in range(rows):
            idx = self.top + i
            if idx >= len(wl):
                break
            c.text(2, _TOP + i * _ROWH, wl[idx], 1)
        c.text(2, c.h - _FH, 'Sel=clear BACK=exit', 1)

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.top += 1
        elif e == ev.ROT_CCW:
            self.top = max(0, self.top - 1)
        elif e == ev.SELECT:
            try:
                import novanotify
                novanotify.clear()
            except Exception:
                pass
            self.top = 0
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class PinScreen(Screen):
    """6-digit PIN entry via the rotary encoder. mode='verify' locks the UI (can't
    be escaped except by the correct PIN); mode='set' stores a new PIN.
    RECOVERY: the serial shell is NOT gated by this, so `reg set Apps.NovaD1_PIN ""`
    always clears it — and a verify screen auto-dismisses when the PIN is cleared."""
    fullscreen = True

    def __init__(self, mode='verify', on_done=None):
        self.title = 'PIN'
        self.mode = mode
        self.digits = [0, 0, 0, 0, 0, 0]
        self.pos = 0
        self.msg = ''
        self.on_done = on_done
        self.next = None

    def draw(self, c):
        ttl = 'SET PIN' if self.mode == 'set' else 'ENTER PIN'
        c.text((c.w - len(ttl) * _ADV) // 2, 3, ttl, 1)
        bw, gap = 14, 4
        total = 6 * bw + 5 * gap
        x0 = (c.w - total) // 2
        y = 26
        for i in range(6):
            x = x0 + i * (bw + gap)
            if i == self.pos:
                c.fill_rect(x, y - 1, bw, _FH + 4, 1); tc = 0
                glyph = str(self.digits[i])        # reveal only the digit you're on
            else:
                c.rect(x, y - 1, bw, _FH + 4, 1); tc = 1
                glyph = '*'                         # others masked
            c.char(x + (bw - _ADV) // 2 + 1, y + 1, ord(glyph), tc)
        foot = self.msg or 'turn=set Sel=move Home=ok'
        c.text((c.w - len(foot[:16]) * _ADV) // 2, c.h - _FH, foot[:16], 1)

    def tick(self, dt_ms=0):
        # Live serial recovery: if the stored PIN is cleared, drop the lock.
        if self.mode == 'verify' and not _reg('Apps.NovaD1_PIN', ''):
            self.next = 'back'
        return False

    def _submit(self):
        pin = ''.join(str(d) for d in self.digits)
        if self.mode == 'set':
            _save_reg('Apps.NovaD1_PIN', pin)
            if self.on_done:
                try:
                    self.on_done(pin)
                except Exception:
                    pass
            return 'back'
        stored = _reg('Apps.NovaD1_PIN', '')
        if not stored or pin == stored:
            return 'back'                       # unlock
        self.msg = 'Wrong PIN'
        self.digits = [0, 0, 0, 0, 0, 0]
        self.pos = 0
        return None

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.digits[self.pos] = (self.digits[self.pos] + 1) % 10
        elif e == ev.ROT_CCW:
            self.digits[self.pos] = (self.digits[self.pos] - 1) % 10
        elif e == ev.SELECT:
            self.pos = (self.pos + 1) % 6       # advance, looping around the 6 digits
        elif e == ev.HOME:
            return self._submit()               # HOME = enter/login (loop digits first)
        elif e == ev.BACK:
            if self.pos > 0:
                self.pos -= 1
            elif self.mode == 'set':
                return 'back'                   # cancel a set (verify can't escape)
        return None


def _nmea_dec(v, hemi):
    """NMEA ddmm.mmmm -> signed decimal degrees string."""
    if not v:
        return ''
    try:
        dot = v.index('.')
        dl = dot - 2
        dec = int(v[:dl]) + float(v[dl:]) / 60.0
        if hemi in ('S', 'W'):
            dec = -dec
        return '{:.5f}'.format(dec)
    except Exception:
        return v


class GPSScreen(Screen):
    """Live GPS — parses NMEA continuously: fix + decimal coords + altitude +
    satellites (used via GGA, in-view via GSV) + speed (RMC). Select saves a
    waypoint to the Nova store. Backed by the verified NEO-M8N RX."""
    def __init__(self):
        self.title = 'GPS'
        self.u = None
        self.err = None
        self.buf = b''
        self.fix = None        # (lat_dec, lon_dec)
        self.alt = ''
        self.used = '0'
        self.inview = '0'
        self.spd = ''
        self.msg = ''
        try:
            import machine
            tx = int(_reg('Apps.NovaD1_PIN_gps_tx', 17))
            rx = int(_reg('Apps.NovaD1_PIN_gps_rx', 18))
            self.u = machine.UART(1, baudrate=9600, tx=machine.Pin(tx), rx=machine.Pin(rx))
        except Exception as e:
            self.err = str(e)[:16]

    def draw(self, c):
        if self.u is None:
            c.text(2, _TOP, 'GPS: ' + (self.err or 'n/a'), 1)
            c.text(2, c.h - _FH, 'BACK = exit', 1)
            return
        y = _TOP
        if self.fix:
            c.text(2, y, 'FIX  sats ' + self.used, 1); y += _ROWH
            c.text(2, y, self.fix[0], 1); y += _ROWH
            c.text(2, y, self.fix[1], 1); y += _ROWH
            c.text(2, y, 'alt ' + (self.alt or '?') + ' ' + (self.spd and self.spd + 'k/h' or ''), 1)
        else:
            c.text(2, y, 'searching...', 1); y += _ROWH
            c.text(2, y, 'in view: ' + self.inview, 1); y += _ROWH
            c.text(2, y, 'used: ' + self.used, 1); y += _ROWH
            c.text(2, y, '(needs sky view)', 1)
        foot = self.msg or ('Sel=save BACK=exit' if self.fix else 'BACK=exit')
        c.text(2, c.h - _FH, foot[:16], 1)

    def tick(self, dt_ms=0):
        if self.u is None:
            return False
        changed = False
        try:
            while self.u.any():
                d = self.u.read()
                if not d:
                    break
                self.buf += d
                while b'\n' in self.buf:
                    line, self.buf = self.buf.split(b'\n', 1)
                    try:
                        s = line.decode('ascii', 'ignore')
                    except Exception:
                        continue
                    f = s.split(',')
                    if 'GGA' in s and len(f) > 9:
                        if f[6] not in ('', '0'):
                            self.fix = (_nmea_dec(f[2], f[3]), _nmea_dec(f[4], f[5]))
                            self.alt = f[9]
                        else:
                            self.fix = None
                        self.used = f[7] or '0'
                        changed = True
                    elif 'GSV' in s and len(f) > 3 and f[3].strip().isdigit():
                        self.inview = f[3].strip()
                        changed = True
                    elif 'RMC' in s and len(f) > 7 and f[7]:
                        try:
                            self.spd = '{:.1f}'.format(float(f[7]) * 1.852)
                        except Exception:
                            pass
        except Exception:
            pass
        return changed

    def _save(self):
        if not self.fix:
            self.msg = 'no fix to save'
            return
        try:
            import novad1
            path = novad1._nova_base() + '/waypoints.txt'
            with open(path, 'a') as fh:
                fh.write('{},{}\n'.format(self.fix[0], self.fix[1]))
            self.msg = 'Saved waypoint'
        except Exception:
            self.msg = 'save failed'

    def on_event(self, e):
        if e == ev.SELECT:
            self._save()
            return None
        if e in (ev.BACK, ev.HOME):
            try:
                self.u.deinit()
            except Exception:
                pass
            return e
        return None


class NFCScreen(Screen):
    """NFC reader (PN532) — poll for a tag, show UID + identified type, Select
    saves a real Flipper .nfc file (UID/ATQA/SAK level) to the Nova store so it
    interops with a Flipper Zero. Fires a notification on a new read. Full memory
    dump (NTAG pages / Classic blocks) + emulate/clone are the next increments."""
    def __init__(self):
        self.title = 'NFC'
        self.card = None
        self.uid = None
        self.kind = ''
        self.saved = None        # filename once saved
        self._acc = 0

    def draw(self, c):
        y = _TOP
        c.text(2, y, 'NFC reader', 1); y += _ROWH
        if self.uid:
            c.text(2, y, self.kind[:21], 1); y += _ROWH
            c.text(2, y, self.uid[:21], 1); y += _ROWH
            if len(self.uid) > 21:
                c.text(2, y, self.uid[21:42], 1); y += _ROWH
        else:
            c.text(2, y, 'tap a tag...', 1)
        if self.saved:
            foot = 'Saved .nfc'
        elif self.uid:
            foot = 'Sel=save BACK=exit'
        else:
            foot = 'BACK=exit'
        c.text(2, c.h - _FH, foot[:21], 1)

    def tick(self, dt_ms=0):
        self._acc += dt_ms or 16
        if self._acc < 400:                      # throttle the ~120ms poll
            return False
        self._acc = 0
        try:
            import novamods, novanfc
            card = novamods.pn532_read_card()
            if card and (self.card is None or card['uid'] != self.card['uid']):
                self.card = card
                self.uid = novanfc.hexs(card['uid'])
                dt2, sub = novanfc.identify(card['sak'], card['atqa'])
                self.kind = sub or dt2
                self.saved = None
                try:
                    import novanotify
                    novanotify.notify('NFC ' + self.kind[:10] + ' ' + self.uid[:11])
                except Exception:
                    pass
                return True
        except Exception:
            pass
        return False

    def on_event(self, e):
        if e == ev.SELECT and self.card:
            return NfcSaveScreen(self.card)      # cooperative dump+save (progress+cancel)
        if e in (ev.BACK, ev.HOME):
            return e
        return None


class NfcSaveScreen(Screen):
    """Reads a tapped card fully and saves a .nfc — on its OWN screen with live
    progress + cancel, so a slow Mifare Classic dump (sector-by-sector) never
    freezes the UI. NTAG/Ultralight = full page dump; Classic = default-key block
    dump (unreadable sectors saved as '??'); anything else = UID-level."""
    def __init__(self, card):
        self.title = 'NFC Save'
        self.card = card
        self.state = 'init'
        self.msg = 'reading...'
        self.saved = None
        self._cancel = False
        self._gen = None
        self._kind = None

    def draw(self, c):
        import novanfc
        dt2, sub = novanfc.identify(self.card['sak'], self.card['atqa'])
        c.text(2, _TOP, 'Save: ' + (sub or dt2)[:15], 1)
        c.text(2, _TOP + _ROWH, novanfc.hexs(self.card['uid'])[:21], 1)
        c.text(2, _TOP + 2 * _ROWH, self.msg[:21], 1)
        c.text(2, c.h - _FH, ('BACK=exit' if self.state == 'done' else 'BACK=cancel'), 1)

    def _save(self, doc):
        import novanfc, novastore
        name = 'card_' + novanfc.hexs(self.card['uid'], '').lower() + '.nfc'
        novastore.save_code('nfc', name, doc.to_text())
        self.saved = name
        self.msg = 'Saved ' + name[:14]

    def _save_uid(self):
        import novanfc
        self._save(novanfc.build_iso14443a(
            self.card['uid'], self.card['atqa'], self.card['sak']))

    def tick(self, dt_ms=0):
        import novamods, novanfc
        if self.state == 'init':
            dt2, sub = novanfc.identify(self.card['sak'], self.card['atqa'])
            if dt2 == novanfc.DT_ULTRALIGHT:
                self._gen = novamods.pn532_dump_ntag(lambda: self._cancel)
                self._kind = 'ntag'
                self.state = 'dump'
                self.msg = 'reading pages...'
            elif dt2 == novanfc.DT_CLASSIC:
                self._gen = novamods.pn532_dump_classic(lambda: self._cancel)
                self._kind = 'classic'
                self.state = 'dump'
                self.msg = 'reading sectors...'
            else:
                self._save_uid()                  # UID-only / unsupported card
                self.state = 'done'
            return True
        if self.state == 'dump':
            try:
                ev2 = next(self._gen)
            except StopIteration:
                ev2 = ('fail', None)
            if ev2[0] == 'progress':
                self.msg = '{} {}/{}'.format(
                    'page' if self._kind == 'ntag' else 'block', ev2[1], ev2[2])
                return True
            if ev2[0] == 'done' and ev2[1] is not None:
                d = ev2[1]
                if self._kind == 'ntag' and d.get('pages'):
                    self._save(novanfc.build_ultralight(
                        d['uid'], d['atqa'], d['sak'], d['ntag_type'], d['pages'],
                        signature=d.get('signature'), mifare_version=d.get('mifare_version')))
                elif self._kind == 'classic':
                    self._save(novanfc.build_classic(
                        d['uid'], d['atqa'], d['sak'], d['mc_type'], d['blocks']))
                else:
                    self._save_uid()              # NTAG with no pages -> UID fallback
            else:
                self._save_uid()                  # read failed/cancelled: keep the UID
                if self._cancel:
                    self.msg = 'cancelled (saved UID)'
            self.state = 'done'
            return True
        return False

    def animating(self):
        return self.state not in ('done',)       # keep ticking through the dump

    def on_event(self, e):
        if e in (ev.BACK, ev.HOME):
            self._cancel = True
            return e
        return None


def _nfc_emulate(text):
    """Fire a saved card. Emulation (TgInitAsTarget) is the NEXT increment, so for
    now this surfaces the UID + an honest 'coming' note instead of pretending."""
    try:
        import novanfc, novanotify
        uid = novanfc.hexs(novanfc.parse(text).uid())
        novanotify.notify('Emulate ' + uid[:14] + ' (next build)')
    except Exception:
        pass


def _nfc_app():
    """NFC home: a list of SAVED cards (run/emulate from flash) + a '+ New' entry to
    scan & save — same shape as the IR/Sub-GHz/LoRa apps, so the app opens to a menu
    instead of jumping straight into scanning."""
    return CodeListScreen('NFC', 'nfc', _nfc_emulate,
                          capture_factory=NFCScreen, fire_label='emulate')


class CodeListScreen(Screen):
    """Browse saved code files for a tool and FIRE them (load hex/timing from a
    file and transmit — no capture needed). Optional '+ New' opens a capture
    screen. Codes live in the Nova store (flash, SD-backed). fire_fn(text)."""
    def __init__(self, title, cat, fire_fn, capture_factory=None, fire_label='fire',
                 fire_screen=None):
        self.title = title
        self.cat = cat
        self.fire = fire_fn
        self.capf = capture_factory
        self.fire_label = fire_label
        self.fire_screen = fire_screen          # (name, text) -> Screen to PUSH (so
        #                                         a blocking TX runs on its own screen
        #                                         with status + cancel, not inline)
        self.sel = 0
        self.top = 0
        self.msg = ''
        self._confirm = None
        self._reload()

    def _reload(self):
        import novastore
        self.rows = (['+ New'] if self.capf else []) + novastore.list_codes(self.cat)
        if self.sel >= len(self.rows):
            self.sel = max(0, len(self.rows) - 1)

    def draw(self, c):
        rows = (c.h - _TOP - _FH) // _ROWH
        if not self.rows:
            c.text(2, _TOP, '(no codes)', 1)
            c.text(2, _TOP + _ROWH, 'add via web/SD', 1)
            c.text(2, c.h - _FH, 'BACK = exit', 1)
            return
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.rows):
                break
            y = _TOP + i * _ROWH
            label = self.rows[idx][:(c.w - 8) // _ADV]
            if idx == self.sel:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                c.text(4, y, label, 0)
            else:
                c.text(4, y, label, 1)
        c.text(2, c.h - _FH, (self.msg or ('Sel=' + self.fire_label))[:16], 1)

    def on_event(self, e):
        if not self.rows:
            if e in (ev.BACK, ev.HOME):
                return e
            return None
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(self.rows)
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(self.rows)
        elif e == ev.SELECT:
            r = self.rows[self.sel]
            if self.capf and r == '+ New':
                return self.capf()
            import novastore
            txt = novastore.read_code(self.cat, r)
            if txt is None:
                self.msg = 'read failed'
                self._confirm = None
                return None
            if self.fire_screen is not None:
                self._confirm = None
                return self.fire_screen(r, txt)  # push a run screen (status+cancel)
            try:
                self.fire(txt)
                self.msg = self.fire_label + ': ' + r[:9]
            except Exception:
                self.msg = 'fire failed'
            self._confirm = None
            return None
        elif e == ev.HOME:                      # native delete (HOME, confirm)
            r = self.rows[self.sel]
            if self.capf and r == '+ New':
                return None
            if self._confirm == r:
                import novastore
                novastore.delete_code(self.cat, r)
                self._confirm = None
                self.msg = 'deleted'
                self._reload()
            else:
                self._confirm = r
                self.msg = 'Home=del?'
            return None
        elif e == ev.BACK:
            self._confirm = None
            return 'back'
        return None

    def tick(self, dt_ms=0):
        if getattr(self, '_dirty', False):
            self._dirty = False
            self._reload()
            return True
        return False


class IRCaptureScreen(Screen):
    """Record a raw IR burst and save it as a Flipper-compatible .ir file."""
    def __init__(self):
        self.title = 'Record IR'
        self.msg = 'point remote + Sel'
        self._cap = False

    def draw(self, c):
        c.text(2, _TOP, 'Record IR', 1)
        c.text(2, _TOP + _ROWH, self.msg[:16], 1)
        c.text(2, c.h - _FH, 'Sel=rec BACK=exit', 1)

    def tick(self, dt_ms=0):
        if not self._cap:
            return False
        self._cap = False
        try:
            import novair
            import novastore
            t = novair.capture(8000)
            if t:
                try:
                    import utime
                    lt = utime.localtime()
                    name = 'ir_{:02d}{:02d}{:02d}'.format(lt[3], lt[4], lt[5])
                except Exception:
                    name = 'ir_code'
                novastore.save_code('ir', name + '.ir', novair.to_flipper(name, t))
                self.msg = 'Saved ' + name
            else:
                self.msg = 'no signal'
        except Exception:
            self.msg = 'capture error'
        return True

    def on_event(self, e):
        if e == ev.SELECT and not self._cap:
            self.msg = 'recording...'
            self._cap = True
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


class IRSignalsScreen(Screen):
    """Buttons inside one .ir file (a remote). Select replays the signal."""
    def __init__(self, fname, sigs):
        self.title = fname[:14]
        self.sigs = sigs           # [(name, freq, duty, times)]
        self.sel = 0
        self.top = 0
        self.msg = ''

    def draw(self, c):
        rows = (c.h - _TOP - _FH) // _ROWH
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.sigs):
                break
            y = _TOP + i * _ROWH
            label = self.sigs[idx][0][:(c.w - 8) // _ADV]
            if idx == self.sel:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                c.text(4, y, label, 0)
            else:
                c.text(4, y, label, 1)
        c.text(2, c.h - _FH, (self.msg or 'Sel=send BACK=back')[:16], 1)

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(self.sigs)
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(self.sigs)
        elif e == ev.SELECT:
            n, fr, du, times = self.sigs[self.sel]
            try:
                import novair
                novair.replay(times, fr, du)
                self.msg = 'sent: ' + n[:9]
            except Exception:
                self.msg = 'fire failed'
            return None
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class IRFilesScreen(Screen):
    """IR code library: list .ir files (remotes). '+ Record' captures a new one;
    a 1-signal file fires directly, a multi-signal remote opens its button list.
    Home = delete (confirm). Flipper .ir files drop straight in."""
    title = 'IR'

    def __init__(self):
        self.sel = 0
        self.top = 0
        self.msg = ''
        self._confirm = None

    def _files(self):
        import novastore
        return novastore.list_codes('ir')

    def draw(self, c):
        rows_list = ['+ Record'] + self._files()
        if self.sel >= len(rows_list):
            self.sel = len(rows_list) - 1
        rows = (c.h - _TOP - _FH) // _ROWH
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= len(rows_list):
                break
            y = _TOP + i * _ROWH
            label = rows_list[idx][:(c.w - 8) // _ADV]
            if idx == self.sel:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                c.text(4, y, label, 0)
            else:
                c.text(4, y, label, 1)
        c.text(2, c.h - _FH, (self.msg or 'Sel=open Home=del')[:16], 1)

    def on_event(self, e):
        rows_list = ['+ Record'] + self._files()
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(rows_list)
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(rows_list)
        elif e == ev.SELECT:
            r = rows_list[self.sel]
            self._confirm = None
            if r == '+ Record':
                return IRCaptureScreen()
            import novastore
            import novair
            sigs = novair.parse_flipper(novastore.read_code('ir', r) or '')
            if not sigs:
                self.msg = 'empty file'
                return None
            if len(sigs) == 1:
                n, fr, du, times = sigs[0]
                try:
                    novair.replay(times, fr, du)
                    self.msg = 'sent'
                except Exception:
                    self.msg = 'fire failed'
                return None
            return IRSignalsScreen(r, sigs)
        elif e == ev.HOME:
            r = rows_list[self.sel]
            if r == '+ Record':
                return None
            if self._confirm == r:
                import novastore
                novastore.delete_code('ir', r)
                self._confirm = None
                self.sel = 0
                self.msg = 'deleted'
            else:
                self._confirm = r
                self.msg = 'Home=del?'
            return None
        elif e == ev.BACK:
            self._confirm = None
            return 'back'
        return None


def _ir_app():
    return IRFilesScreen()


class SubGhzFireScreen(Screen):
    """Transmit a saved Sub-GHz code on its OWN screen — checks the CC1101 is there
    first, shows a live 'Transmitting...' status (so it never looks frozen), and
    BACK cancels (between bursts; a single burst is too timing-critical to cut
    mid-air). Fixes: silent freeze / no cancel / no module check on the old inline
    fire."""
    def __init__(self, name, text):
        self.title = 'Sub-GHz TX'
        self.name = name
        self.text = text
        self.state = 'check'
        self.msg = 'checking module...'
        self._cancel = False

    def draw(self, c):
        c.text(2, _TOP, 'Sub-GHz TX', 1)
        c.text(2, _TOP + _ROWH, self.name[:21], 1)
        c.text(2, _TOP + 2 * _ROWH, self.msg[:21], 1)
        c.text(2, c.h - _FH, ('BACK=exit' if self.state == 'done' else 'BACK=cancel'), 1)

    def tick(self, dt_ms=0):
        if self.state == 'check':
            try:
                import novacc
                ok = novacc.present()
            except Exception:
                ok = False
            if not ok:
                self.msg = 'No CC1101 found'
                self.state = 'done'
            else:
                self.msg = 'Transmitting...'     # shown BEFORE the blocking burst
                self.state = 'tx'
            return True
        if self.state == 'tx':
            try:
                import novacc
                fired = novacc.fire_text(self.text, repeats=4,
                                         cancel=lambda: self._cancel)
                self.msg = ('Cancelled' if self._cancel
                            else ('Sent' if fired else 'TX failed'))
            except Exception:
                self.msg = 'TX error'
            self.state = 'done'
            return True
        return False

    def on_event(self, e):
        if e in (ev.BACK, ev.HOME):
            self._cancel = True                  # abort between bursts, then exit
            return e
        return None


def _subghz_app():
    return CodeListScreen('Sub-GHz', 'subghz', lambda t: None, fire_label='TX',
                          fire_screen=lambda n, t: SubGhzFireScreen(n, t))


class BlePingScreen(Screen):
    """Broadcast a 'device nearby' pairing advertisement so YOUR phone shows the
    pairing card. NON-BLOCKING — the BLE radio advertises on its own while this
    screen counts down, so the UI never freezes; BACK stops immediately. Point it
    at your own phone (own-device / authorized use)."""
    def __init__(self, platform='apple', model=None, secs=12):
        self.title = 'BLE Ping'
        self.platform = platform
        self.model = model
        self.secs = secs
        self.msg = 'starting...'
        self._t0 = None
        self._done = False

    def draw(self, c):
        c.text(2, _TOP, 'BLE Ping: ' + self.platform, 1)
        c.text(2, _TOP + _ROWH, (self.model or 'default')[:21], 1)
        c.text(2, _TOP + 2 * _ROWH, self.msg[:21], 1)
        c.text(2, c.h - _FH, 'BACK=stop', 1)

    def tick(self, dt_ms=0):
        import utime
        if self._done:
            return False
        if self._t0 is None:
            try:
                import novable
                if not novable.available():
                    self.msg = 'no BLE on board'
                    self._done = True
                    return True
                m = novable.start_ping(self.platform, self.model)
                self.model = m or self.model
                self._t0 = utime.ticks_ms()
                self.msg = 'advertising...'
            except Exception:
                self.msg = 'BLE error'
                self._done = True
            return True
        left = self.secs - utime.ticks_diff(utime.ticks_ms(), self._t0) // 1000
        if left <= 0:
            self._stop()
            self.msg = 'done'
            self._done = True
            return True
        nm = 'check your phone ({}s)'.format(left)
        if nm != self.msg:
            self.msg = nm
            return True
        return False

    def _stop(self):
        try:
            import novable
            novable.stop()
        except Exception:
            pass

    def animating(self):
        return not self._done                    # keep ticking for the countdown

    def on_event(self, e):
        if e in (ev.BACK, ev.HOME):
            self._stop()
            return e
        return None


def _ble_app():
    return Menu('BLE', [
        ('Scan nearby', lambda: ModuleTestScreen('bt', 'Bluetooth')),
        ('Ping iPhone', lambda: BlePingScreen('apple')),
        ('Ping Android', lambda: BlePingScreen('android')),
    ])


class LedScreen(Screen):
    """Control the WS2812 status LED — turn the encoder to pick a colour (applied
    LIVE so the LED changes as you turn), Select to keep it. A real app in place of
    the old LED hardware-test."""
    COLORS = [('Off', (0, 0, 0)), ('Red', (120, 0, 0)), ('Orange', (120, 45, 0)),
              ('Yellow', (110, 110, 0)), ('Green', (0, 120, 0)), ('Cyan', (0, 110, 110)),
              ('Blue', (0, 0, 150)), ('Purple', (95, 0, 130)), ('Pink', (130, 20, 70)),
              ('White', (90, 90, 90)), ('Warm', (120, 65, 20))]

    def __init__(self):
        self.title = 'LED'
        self.sel = 0
        self.msg = 'turn = pick   Sel = set'
        self._apply()

    def _apply(self):
        try:
            import novamods
            novamods.set_led(*self.COLORS[self.sel][1])
        except Exception:
            pass

    def draw(self, c):
        name, (r, g, b) = self.COLORS[self.sel]
        c.text(2, _TOP, 'Status LED', 1)
        c.text(2, _TOP + _ROWH, name, 1)
        c.rect(c.w - 40, _TOP - 1, 34, 2 * _ROWH, 1)         # swatch frame
        if r or g or b:
            c.fill_rect(c.w - 38, _TOP + 1, 30, 2 * _ROWH - 4, 1)
        else:
            c.text(c.w - 33, _TOP + _ROWH - 3, 'off', 1)
        n = len(self.COLORS)                                 # palette position dots
        y = _TOP + 2 * _ROWH + 3
        for i in range(n):
            x = 2 + i * 7
            if i == self.sel:
                c.fill_rect(x, y, 5, 5, 1)
            else:
                c.rect(x, y, 5, 5, 1)
        c.text(2, c.h - _FH, self.msg[:21], 1)

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(self.COLORS)
            self._apply()
            self.msg = 'turn = pick   Sel = set'
            return None
        if e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(self.COLORS)
            self._apply()
            self.msg = 'turn = pick   Sel = set'
            return None
        if e == ev.SELECT:
            self.msg = 'set: ' + self.COLORS[self.sel][0]
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


class BatteryScreen(Screen):
    """Live battery status — %, a bar, voltage, USB/charging. A real app in place of
    the battery hardware-test. Reads novapower once a second."""
    def __init__(self):
        self.title = 'Battery'
        self._acc = 0
        self.d = None
        self._read()

    def _read(self):
        try:
            import novapower
            self.d = novapower.read()
        except Exception:
            self.d = None

    def draw(self, c):
        c.text(2, _TOP, 'Battery', 1)
        d = self.d or {}
        if not d.get('have'):
            c.text(2, _TOP + _ROWH, 'No battery detected', 1)
            c.text(2, _TOP + 2 * _ROWH, 'set Apps.NovaD1_PIN_battery', 1)
        else:
            pct = d.get('pct', 0)
            bw = c.w - 8
            c.rect(2, _TOP + _ROWH, bw, 11, 1)
            c.fill_rect(4, _TOP + _ROWH + 2, int((bw - 4) * pct / 100), 7, 1)
            c.text(2, _TOP + 2 * _ROWH + 2, '{}%   {:.2f} V'.format(pct, d.get('volts', 0)), 1)
            usb = d.get('usb')
            usbs = 'charging' if usb else ('on battery' if usb is not None else 'USB ?')
            c.text(2, _TOP + 3 * _ROWH + 2, usbs + ('  LOW' if d.get('low') else ''), 1)
        c.text(2, c.h - _FH, 'BACK = exit', 1)

    def tick(self, dt_ms=0):
        self._acc += dt_ms or 16
        if self._acc >= 1000:
            self._acc = 0
            self._read()
            return True
        return False

    def on_event(self, e):
        if e in (ev.BACK, ev.HOME):
            return e
        return None


class EnvironmentScreen(Screen):
    """Live temperature + humidity (DHT11) with min/max. A real app in place of the
    DHT hardware-test."""
    def __init__(self):
        self.title = 'Environment'
        self._acc = 0
        self.t = None
        self.h = None
        self.tmin = None
        self.tmax = None

    def _read(self):
        try:
            import novamods
            r = novamods.read_dht()
        except Exception:
            r = None
        if r:
            self.t, self.h = r
            self.tmin = self.t if self.tmin is None else min(self.tmin, self.t)
            self.tmax = self.t if self.tmax is None else max(self.tmax, self.t)

    def draw(self, c):
        c.text(2, _TOP, 'Environment', 1)
        if self.t is None:
            c.text(2, _TOP + _ROWH, 'reading...', 1)
            c.text(2, _TOP + 2 * _ROWH, '(no DHT? check pin)', 1)
        else:
            c.text(2, _TOP + _ROWH, 'Temp:  {} C'.format(self.t), 1)
            c.text(2, _TOP + 2 * _ROWH, 'Humid: {} %'.format(self.h), 1)
            if self.tmin is not None:
                c.text(2, _TOP + 3 * _ROWH + 2, 'min {}  max {}'.format(self.tmin, self.tmax), 1)
        c.text(2, c.h - _FH, 'BACK = exit', 1)

    def tick(self, dt_ms=0):
        self._acc += dt_ms or 16
        if self.t is None or self._acc >= 2000:
            self._acc = 0
            self._read()
            return True
        return False

    def on_event(self, e):
        if e in (ev.BACK, ev.HOME):
            return e
        return None


def _lora_tx_app():
    return CodeListScreen('LoRa TX', 'lora', _lora_fire, fire_label='send')


def _lora_fire(t):
    import novamsg
    novamsg.send(t.strip())


class ButtonGridScreen(Screen):
    """A 'remote' — a 2-column grid of buttons, each running a nova action string
    ('ir tv.ir Power', 'lora hi', 'subghz gate', 'run sysinfo', 'notify ...')."""
    def __init__(self, title, buttons):
        self.title = title[:14]
        self.buttons = buttons               # [(label, action)]
        self.sel = 0
        self.msg = ''

    def draw(self, c):
        if not self.buttons:
            c.text(2, _TOP, '(no buttons)', 1)
            c.text(2, c.h - _FH, 'BACK = exit', 1)
            return
        cols = 2
        bw = (c.w - 6) // cols
        bh = _ROWH + 4
        rows_vis = max(1, (c.h - _TOP - _FH) // bh)
        per = cols * rows_vis
        start = (self.sel // per) * per
        for i in range(per):
            idx = start + i
            if idx >= len(self.buttons):
                break
            r = i // cols
            col = i % cols
            x = 3 + col * bw
            y = _TOP + r * bh
            lbl = self.buttons[idx][0][:(bw - 5) // _ADV]
            if idx == self.sel:
                c.fill_rect(x, y, bw - 2, bh - 2, 1)
                c.text(x + 3, y + 2, lbl, 0)
            else:
                c.rect(x, y, bw - 2, bh - 2, 1)
                c.text(x + 3, y + 2, lbl, 1)
        c.text(2, c.h - _FH, (self.msg or 'Sel=run BACK=exit')[:16], 1)

    def on_event(self, e):
        n = len(self.buttons)
        if not n:
            return e if e in (ev.BACK, ev.HOME) else None
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % n
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % n
        elif e == ev.SELECT:
            import nova
            self.msg = nova.do(self.buttons[self.sel][1])
            return None
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class ScriptsScreen(Screen):
    """Script launcher: lists files in the scripts store. A button-grid script
    opens as a remote; a .py script runs with the nova API. Upload via the web."""
    title = 'Scripts'

    def __init__(self):
        self.sel = 0
        self.top = 0
        self.msg = ''

    def _files(self):
        import novastore
        return novastore.list_codes('scripts')

    def draw(self, c):
        files = self._files()
        if not files:
            c.text(2, _TOP, '(no scripts)', 1)
            c.text(2, _TOP + _ROWH, 'upload via web', 1)
            c.text(2, c.h - _FH, 'BACK = exit', 1)
            return
        rows = (c.h - _TOP - _FH) // _ROWH
        if self.sel >= len(files):
            self.sel = len(files) - 1
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= len(files):
                break
            y = _TOP + i * _ROWH
            label = files[idx][:(c.w - 8) // _ADV]
            if idx == self.sel:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                c.text(4, y, label, 0)
            else:
                c.text(4, y, label, 1)
        c.text(2, c.h - _FH, (self.msg or 'Sel=open BACK=exit')[:16], 1)

    def on_event(self, e):
        files = self._files()
        if not files:
            return e if e in (ev.BACK, ev.HOME) else None
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(files)
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(files)
        elif e == ev.SELECT:
            import novastore
            import nova
            name = files[self.sel]
            txt = novastore.read_code('scripts', name) or ''
            if name.endswith('.py'):
                ok, err = nova.run_py(txt)
                self.msg = 'ran ok' if ok else ('err: ' + err)[:15]
                return None
            title, btns = nova.parse_buttons(txt)
            if btns:
                return ButtonGridScreen(title, btns)
            self.msg = 'no buttons'
            return None
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class LowPowerScreen(Screen):
    """Transient low-battery popup — auto-dismisses; any key clears it."""
    DUR = 3000

    def __init__(self):
        self.title = 'Battery'
        self.t = 0
        self.next = None

    def draw(self, c):
        bw, bh = 110, 32
        x = (c.w - bw) // 2
        y = (c.h - bh) // 2
        c.fill_rect(x, y, bw, bh, 0)
        c.rect(x, y, bw, bh, 1)
        c.rect(x + 1, y + 1, bw - 2, bh - 2, 1)
        c.text(x + 8, y + 6, 'LOW BATTERY', 1)
        c.text(x + 8, y + 17, 'charge soon', 1)

    def tick(self, dt_ms=0):
        self.t += dt_ms or 16
        if self.t >= self.DUR:
            self.next = 'back'
        return False

    def on_event(self, e):
        self.next = 'back'
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
    def __init__(self, display, canvas, source, state_provider, home, home_factory=None):
        self.display = display
        self.canvas = canvas
        self.source = source
        self.state = state_provider
        self.stack = [home]
        self.home_factory = home_factory      # () -> fresh home screen, for live rebuild
        self._stop = False
        self._state_cache = None
        self._state_t = -100000
        self._last_render = 0
        self._idle_t0 = 0
        self._level = 0              # idle power tier: 0 active, 1 dimmed, 2 off
        self._dimmed = False         # = level >= 1 (kept for existing call sites)
        self._locked = False         # a PIN lock screen is currently pushed
        self._lock_scr = None
        self._low_warned = False
        self._last_sig = None
        self._render_us = 0          # last render time (us) — perf instrumentation
        self._render_max = 0         # worst render since reset
        self._shows = 0

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

    def _set_level(self, level):
        """Idle power tier via CONTRAST only — NEVER power-off, so it's 100%
        recoverable (power(False) could leave a panel that won't wake — the reported
        brick). 0 = active (full brightness), 1 = dimmed (low but readable), 2 = off
        (near-black). The loop keeps polling input the whole time."""
        if level == self._level:
            return
        self._level = level
        self._dimmed = level >= 1
        d = self.display
        try:
            if level == 0:
                d.contrast(int(_reg('Apps.NovaD1_Contrast', 255)))
                d.invalidate()                   # force a full redraw next frame
            elif level == 1:
                full = int(_reg('Apps.NovaD1_Contrast', 255))
                d.contrast(full // 6 if full // 6 > 0 else 1)
            else:
                # contrast(0) on an SH1106 is dim, NOT off — lit pixels stay faintly
                # visible. So also BLANK the framebuffer once -> a truly black screen,
                # still 100% recoverable (no power-off command, no brick). Wake
                # re-renders via the invalidate in level 0.
                d.contrast(0)
                try:
                    self.canvas.clear(0)
                    d.invalidate()
                    d.show(self.canvas)
                except Exception:
                    pass
        except Exception:
            pass

    def sleep_display(self):
        self._set_level(2)

    def _wake_display(self):
        self._set_level(0)

    def _loop_once(self, prev, sleep_ms):
        now = self._now()
        dt = now - prev
        dirty = False
        # Drain ALL pending input events this turn — the encoder IRQ can queue many
        # steps between turns; processing one per turn made fast spins/held buttons
        # 'spread out over time'. Applying them all here keeps input snappy.
        e = self.source.poll()
        if e is not None and self._dimmed:       # WAKE only — swallow everything queued
            self._wake_display()
            self._idle_t0 = now                  # reset idle so it doesn't re-dim at once
            dirty = True
            while self.source.poll() is not None:
                pass
            e = None
        while e is not None:
            self._idle_t0 = now
            dirty = self.handle(e) or dirty
            e = self.source.poll()
        # Rebuild the home live when its config changed (apps/style) and we're back
        # on it — no reboot needed.
        global _home_dirty
        if _home_dirty and len(self.stack) == 1 and self.home_factory is not None:
            try:
                self.stack[0] = self.home_factory()
            except Exception:
                pass
            _home_dirty = False
            dirty = True
        scr = self.stack[-1]
        if scr.tick(dt):
            dirty = True
        nx = getattr(scr, 'next', None)          # a screen can auto-advance itself
        if nx is not None:
            scr.next = None
            self._apply(nx)
            dirty = True
        # Re-render only when the status bar's VISIBLE state actually changes (the
        # minute, wifi/battery/notify/save icons) — not every second. A full redraw
        # is tens of ms of non-yielding work; doing it 1x/sec was starving the
        # serial shell's keystroke reader on the shared event loop.
        st = self._get_state(now)
        pwr = st.get('power') or {}
        sig = (st.get('time'), st.get('wifi'), st.get('notify'), st.get('saving'),
               pwr.get('pct') if pwr else None, pwr.get('usb') if pwr else None,
               pwr.get('low') if pwr else None)
        if sig != self._last_sig:
            self._last_sig = sig
            dirty = True
        # Low-battery popup (once per low->ok transition; needs a configured battery).
        if pwr.get('low'):
            if not self._low_warned and not self._dimmed:
                self._low_warned = True
                self.stack.append(LowPowerScreen())
                try:
                    import novanotify
                    novanotify.notify('Low battery')
                except Exception:
                    pass
                dirty = True
        else:
            self._low_warned = False
        # Idle power tiers: active -> dim (DimSec) -> off (OffSec) -> lock
        # (OffSec+LockSec, only if a PIN is set). 0 disables a tier. All via
        # contrast, never power-off, so it's always recoverable.
        idle = now - self._idle_t0
        dim_s = _int_reg('Apps.NovaD1_DimSec', 15)
        off_s = _int_reg('Apps.NovaD1_OffSec', 60)
        lock_s = _int_reg('Apps.NovaD1_LockSec', 5)
        if off_s > 0 and idle >= off_s * 1000:
            target = 2
        elif dim_s > 0 and idle >= dim_s * 1000:
            target = 1
        else:
            target = 0
        if target != self._level:
            self._set_level(target)
            if target == 0:
                dirty = True
        # Auto-lock a short while after the screen goes off (needs a set PIN).
        if (target == 2 and not self._locked and off_s > 0 and lock_s >= 0
                and _reg('Apps.NovaD1_PIN', '')
                and idle >= (off_s + lock_s) * 1000):
            self._lock_scr = PinScreen('verify')
            self.stack.append(self._lock_scr)
            self._locked = True
        # The user entered the PIN -> the lock screen popped itself off the stack.
        if self._locked and self._lock_scr is not None and self._lock_scr not in self.stack:
            self._locked = False
            self._lock_scr = None
        if self._level >= 2:
            dirty = False                        # screen off — skip rendering
        if dirty:
            try:
                import utime
                _t = utime.ticks_us()
                self.render(now)
                self._render_us = utime.ticks_diff(utime.ticks_us(), _t)
                if self._render_us > self._render_max:
                    self._render_max = self._render_us
                self._shows += 1
            except Exception:
                self.render(now)
        # Adaptive pace — the GUI shares one cooperative loop with the serial shell,
        # so when the UI is idle it must CEDE cpu (long nap) or it starves the shell's
        # keystroke reader (choppy typing). When you're actually using the UI (recent
        # input) or animating, nap short so the UI stays snappy.
        if self._level >= 2:
            nap = 400                           # off -> deep idle, cede the loop
        elif scr.animating():
            nap = 16                            # smooth animation frames
        elif (now - self._idle_t0) < 1500:
            nap = 33                            # just interacted -> responsive UI
        elif self._level == 1:
            nap = 250                           # dimmed but visible -> slow refresh
        else:
            nap = 160                           # idle -> hand the loop to the shell
        return now, nap

    def run(self, sleep_ms=40):
        global _active_ui
        _active_ui = self
        try:
            import utime as _t
            _sleep = _t.sleep_ms
        except ImportError:
            import time as _tt
            def _sleep(ms): _tt.sleep(ms / 1000.0)
        self._stop = False
        self._idle_t0 = self._now()
        self.render()
        prev = self._now()
        while not self._stop:
            prev, nap = self._loop_once(prev, sleep_ms)
            _sleep(nap)

    async def run_async(self, sleep_ms=40):
        # Cooperative loop — runs as a BACKGROUND SERVICE so the serial shell
        # stays free (OLED and shell are separate surfaces). Yields every tick.
        import asyncio
        global _active_ui
        _active_ui = self
        self._stop = False
        self._idle_t0 = self._now()
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


def _power_lock():
    return PinScreen('verify') if _reg('Apps.NovaD1_PIN', '') else None


def _power_sleep():
    # Real screen-off now (+ lock if a PIN is set). NOT machine.lightsleep — that
    # can drop USB-CDC/peripherals and look like a brick. Wake = any button.
    if _active_ui is not None:
        _active_ui.sleep_display()
    return _power_lock()


def _power_exit():
    if _active_ui is not None:
        _active_ui.stop()
    return None


def _power_menu():
    return Menu('Power', [
        ('Lock Now', _power_lock),
        ('Sleep', _power_sleep),
        ('Reboot', lambda: CommandScreen('Reboot', 'sreboot')),
        ('Exit Nova', _power_exit),
    ])


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


# App categories — used by the 'folders' home + a future app manager. An app's key
# maps to one category; unknown keys fall to Tools.
_CATEGORIES = ('Wireless', 'Sensors', 'Tools', 'System')
_APP_CAT = {
    'pn532': 'Wireless', 'bt': 'Wireless', 'cc1101': 'Wireless', 'sx1276': 'Wireless',
    'wifi': 'Wireless', 'ir': 'Wireless', 'msg': 'Wireless',
    'gps': 'Sensors', 'dht11': 'Sensors', 'battery': 'Sensors',
    'scripts': 'Tools', 'notes': 'Tools', 'logs': 'Tools', 'led': 'Tools',
    'store': 'Tools',
    'check': 'System', 'power': 'System', 'settings': 'System', 'diag': 'System',
}
# A representative icon per category (reuses an app icon so folders look distinct).
_CAT_ICON = {'Wireless': 'bt', 'Sensors': 'gps', 'Tools': 'scripts', 'System': 'settings'}

# Modules that are pure hardware probes (no real 'app') — folded into Diagnostics
# instead of cluttering the home.
_DIAG_ONLY = ('buzzer', 'vibration', 'ibutton', 'sdcard')


# Installed script-apps -> their auto-derived category (filled by _script_apps()).
_SCRIPT_CATS = {}
_CAT_OVERRIDE = {}   # user reassignments (persisted): key -> Category


def _load_cat_overrides():
    """Load user category reassignments from Apps.NovaD1_AppCats ('key:Cat,key2:Cat2').
    Called once per home build so a reassigned app lands in the chosen folder."""
    _CAT_OVERRIDE.clear()
    raw = _reg('Apps.NovaD1_AppCats', '') or ''
    for part in raw.split(','):
        if ':' in part:
            k, c = part.split(':', 1)
            k = k.strip()
            c = c.strip()
            if k and c in _CATEGORIES:
                _CAT_OVERRIDE[k] = c
    return _CAT_OVERRIDE


def _save_cat_overrides():
    _save_reg('Apps.NovaD1_AppCats',
              ','.join('{}:{}'.format(k, c) for k, c in _CAT_OVERRIDE.items()))


def _set_cat_override(key, cat):
    """cat in _CATEGORIES pins the app to that home folder; None/'auto' clears the
    override (back to the built-in/auto category). Persists + marks the home dirty."""
    if cat and cat in _CATEGORIES:
        _CAT_OVERRIDE[key] = cat
    else:
        _CAT_OVERRIDE.pop(key, None)
    _save_cat_overrides()
    _mark_home_dirty()


def _app_category(key):
    if key in _CAT_OVERRIDE:      # user reassignment wins
        return _CAT_OVERRIDE[key]
    if key in _SCRIPT_CATS:       # auto-derived for installed script-apps
        return _SCRIPT_CATS[key]
    return _APP_CAT.get(key, 'Tools')


def _mk_script_app(title, btns):
    return lambda: ButtonGridScreen(title, list(btns))


def _script_apps():
    """Installed button-grid script-apps (from the scripts store) as HOME apps,
    auto-categorised by content — so an app you download/drop in appears on the home
    in the right folder, not just in the Scripts list."""
    out = []
    _SCRIPT_CATS.clear()
    try:
        import nova
        import novastore
        import novaappcfg
        for name in novastore.list_codes('scripts'):
            txt = novastore.read_code('scripts', name) or ''
            title, btns = nova.parse_buttons(txt)
            if not btns:
                continue                              # only button grids are apps
            key = 'script_' + name
            _SCRIPT_CATS[key] = novaappcfg.auto_category('buttons', txt)
            out.append((key, (title or name)[:12], _mk_script_app(title or name, btns)))
    except Exception:
        pass
    return out


def _diag_app():
    """Diagnostics: run any module's hardware self-test (absorbs the old per-module
    test icons, and keeps every module reachable for bring-up)."""
    import novamods
    items = []
    for k, label, _fn in novamods.MODULES:
        if k == 'ir_tx':
            continue
        items.append((label, _mk_test(k, label)))
    return Menu('Diagnostics', items)


def _mk_folder(cat, apps):
    return lambda: IconGallery(cat, list(apps))


class AppStoreScreen(Screen):
    """Browse + install Nova apps from the online store (repo/novad1-apps). Fetches
    the index over WiFi — shows 'Fetching...' while it does (HTTPS on the D1 is a few
    seconds) — lists the apps, Select installs one; it lands on the home in its
    auto-category. Cooperative status; the network calls block (async is a later win)."""
    def __init__(self):
        self.title = 'App Store'
        self.state = 'init'
        self.msg = 'Sel=install  BACK=exit'
        self.apps = []
        self.installed = set()
        self.sel = 0
        self.top = 0

    def draw(self, c):
        c.text(2, _TOP, 'App Store', 1)
        if self.state in ('init', 'fetch'):
            c.text(2, _TOP + 2 * _ROWH, 'Fetching store...', 1)
            return
        if self.state == 'error':
            c.text(2, _TOP + _ROWH, self.msg[:21], 1)
            c.text(2, _TOP + 2 * _ROWH, 'need WiFi + web PIN', 1)
            c.text(2, c.h - _FH, 'BACK = exit', 1)
            return
        if not self.apps:
            c.text(2, _TOP + _ROWH, '(no apps found)', 1)
            c.text(2, c.h - _FH, 'BACK = exit', 1)
            return
        rows = (c.h - _TOP - _FH) // _ROWH
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.apps):
                break
            a = self.apps[idx]
            y = _TOP + i * _ROWH
            inst = ' *' if (a.get('dir', '') + '.txt') in self.installed else ''
            label = (a.get('name', '?') + inst)[:(c.w - 8) // _ADV]
            if idx == self.sel:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
                c.text(4, y, label, 0)
            else:
                c.text(4, y, label, 1)
        if self.top + rows < len(self.apps):
            _scroll_tri(c, c.w - 6, c.h - _FH - 5, False)
        c.text(2, c.h - _FH, self.msg[:21], 1)

    def tick(self, dt_ms=0):
        if self.state == 'init':
            self.state = 'fetch'                  # render "Fetching..." first
            return True
        if self.state == 'fetch':
            try:
                import novaappstore
                apps = novaappstore.fetch_index()
                self.installed = novaappstore.installed_names()
            except Exception:
                apps = None
            if apps is None:
                self.msg = 'fetch failed'
                self.state = 'error'
            else:
                self.apps = apps
                self.state = 'list'
            return True
        if self.state == 'installing':
            try:
                import novaappstore
                name = novaappstore.install(self.apps[self.sel])
                self.msg = 'Installed (on home)!' if name else 'install failed'
                if name:
                    self.installed.add(name)
            except Exception:
                self.msg = 'install error'
            self.state = 'list'
            return True
        return False

    def on_event(self, e):
        if self.state == 'list' and self.apps:
            if e == ev.ROT_CW:
                self.sel = (self.sel + 1) % len(self.apps)
                return None
            if e == ev.ROT_CCW:
                self.sel = (self.sel - 1) % len(self.apps)
                return None
            if e == ev.SELECT:
                self.msg = 'Installing...'
                self.state = 'installing'
                return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


def _all_apps():
    """Every possible home app: (key, label, factory). Modules + built-in apps. Real
    apps replace the raw hardware tests; pure probes go to the Diagnostics app."""
    import novamods
    apps = []
    for k, l, _fn in novamods.MODULES:
        if k == 'gps':
            apps.append((k, 'GPS', GPSScreen))
        elif k == 'pn532':
            apps.append((k, 'NFC', _nfc_app))            # saved cards + '+ New' scan
        elif k == 'ir_rx':
            apps.append(('ir', 'IR', _ir_app))          # record/replay + code library
        elif k == 'ir_tx':
            continue                                    # folded into the IR app
        elif k == 'cc1101':
            apps.append((k, 'Sub-GHz', _subghz_app))    # load + fire OOK codes
        elif k == 'sx1276':
            apps.append((k, 'LoRa TX', _lora_tx_app))   # fire saved LoRa payloads
        elif k == 'bt':
            apps.append((k, 'BLE', _ble_app))           # scan + ping (Apple/Android)
        elif k == 'led':
            apps.append((k, 'LED', LedScreen))          # real WS2812 colour control
        elif k == 'dht11':
            apps.append((k, 'Environment', EnvironmentScreen))  # live temp/humidity
        elif k == 'battery':
            apps.append((k, 'Battery', BatteryScreen))   # live %, voltage, charging
        elif k in _DIAG_ONLY:
            continue                                    # -> Diagnostics app
        else:
            apps.append((k, l, _mk_test(k, l)))
    apps.append(('diag', 'Diagnostics', _diag_app))
    apps.append(('store', 'App Store', AppStoreScreen))   # browse + install apps
    apps.append(('wifi', 'WiFi', WiFiScreen))
    apps.append(('msg', 'Messages', MessagesScreen))
    apps.append(('notes', 'Notifications', NotificationsScreen))
    apps.append(('check', 'Sys Check', SystemCheckScreen))
    apps.append(('logs', 'Logs', _logs_screen))
    apps.append(('scripts', 'Scripts', ScriptsScreen))
    apps.append(('power', 'Power', _power_menu))
    apps.extend(_script_apps())              # installed script-apps -> home (auto-cat)
    return apps


def make_boot_stack(home):
    """Boot order: home at the bottom, then the check, then the splash on top —
    splash plays -> pops to check -> check runs -> pops to home."""
    # home at the bottom, splash on top. The splash plays while the boot work runs on
    # the loop, then pops to home. The old visible System Check is hidden (it added
    # boot time + covered the splash); run the SysCheck app on demand instead.
    return [home, SplashScreen()]


def _home_keys():
    """Enabled home apps in order. Registry csv 'Apps.NovaD1_Home'; default all."""
    raw = _reg('Apps.NovaD1_Home')
    if not raw:
        return None
    keys = [k.strip() for k in raw.split(',') if k.strip()]
    return keys or None


def _strip_ansi(s):
    out = ''
    i = 0
    n = len(s)
    while i < n:
        if s[i] == '\x1b':
            j = i + 1
            while j < n and not ('a' <= s[j] <= 'z' or 'A' <= s[j] <= 'Z'):
                j += 1
            i = j + 1
        else:
            out += s[i]
            i += 1
    return out


def _run_capture(cmd):
    """Run an OS shell command, return its output as wrapped display lines."""
    import sys
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
    if lp is None or not hasattr(lp, '_run_line'):
        return ['shell n/a']
    out = ''
    try:
        import io
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            lp._run_line(cmd)
        finally:
            sys.stdout = old
        out = buf.getvalue()
    except Exception:
        try:
            import RPCortex
            RPCortex.begin_capture()
            try:
                lp._run_line(cmd)
            except Exception:
                pass
            out = RPCortex.end_capture() or ''
        except Exception:
            out = ''
    out = _strip_ansi(out)
    lines = []
    cols = (128 - 3) // _ADV
    for ln in out.split('\n'):
        ln = ln.rstrip('\r')
        if ln == '':
            continue
        lines.extend(_wrap(ln, cols))
    return lines[:60] or ['(done)']


class CommandScreen(Screen):
    """Runs an OS command on first tick, shows scrollable output."""
    def __init__(self, title, cmd):
        self.title = title
        self.cmd = cmd
        self.lines = ['Running...']
        self.top = 0
        self._ran = False

    def draw(self, c):
        rows = (c.h - _TOP - _FH) // _ROWH
        if self.top > max(0, len(self.lines) - rows):
            self.top = max(0, len(self.lines) - rows)
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.lines):
                break
            c.text(2, _TOP + i * _ROWH, self.lines[idx], 1)
        c.text(2, c.h - _FH, 'turn=scroll BACK=exit', 1)

    def tick(self, dt_ms=0):
        if not self._ran:
            self._ran = True
            self.lines = _run_capture(self.cmd)
            return True
        return False

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.top += 1
        elif e == ev.ROT_CCW:
            self.top = max(0, self.top - 1)
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class SettingsScreen(Screen):
    """Grouped settings under section headers. Rows:
       ('head', label) — a section title (skipped by navigation)
       ('push', label, factory) — opens a sub-screen
       ('cycle', label, regkey, [values], default, apply) — flips a saved value
       ('action', label, shell-cmd) — runs an OS command, shows output."""
    def __init__(self):
        self.title = 'Settings'
        self.top = 0
        all_for_cfg = [(k, l) for k, l, _f2 in _all_apps() if not k.startswith('script_')]
        cur = _home_keys() or [k for k, _l in all_for_cfg]
        self.rows = [
            ('head', 'DISPLAY'),
            ('push', 'Brightness', DisplayScreen),
            ('cycle', 'Dim After', 'Apps.NovaD1_DimSec', ['0', '5', '15', '30', '60'], '15', None),
            ('cycle', 'Screen Off', 'Apps.NovaD1_OffSec', ['0', '30', '60', '120', '300'], '60', None),
            ('cycle', 'Auto-Lock', 'Apps.NovaD1_LockSec', ['0', '5', '15', '30', '60'], '5', None),
            ('cycle', 'Invert', 'Apps.NovaD1_Invert', ['off', 'on'], 'off', _apply_invert),
            ('cycle', 'Screen', 'Apps.NovaD1_Display', ['sh1106', 'ssd1306'], 'sh1106', None),
            ('head', 'HOME'),
            ('cycle', 'Layout', 'Apps.NovaD1_HomeStyle', ['folders', 'gallery', 'menu'], 'folders', None),
            ('push', 'Manage Apps', lambda: ManageAppsScreen(all_for_cfg, cur)),
            ('cycle', 'Chime', 'Apps.NovaD1_Chime', ['on', 'off'], 'on', None),
            ('cycle', 'Notify', 'Apps.NovaD1_Notify', ['on', 'off'], 'on', None),
            ('head', 'SYSTEM'),
            ('push', 'Set Time', TimeScreen),
            ('push', 'WiFi', WiFiScreen),
            ('cycle', 'Dyn Clock', 'Settings.Dynamic_Clock', ['false', 'true'], 'false', None),
            ('cycle', 'Verbose', 'Settings.Verbose_Boot', ['false', 'true'], 'false', None),
            ('cycle', 'SD Card', 'Features.SD_Support', ['false', 'true'], 'false', None),
            ('head', 'RADIO'),
            ('cycle', 'LoRa MHz', 'Apps.NovaD1_LoRa_Freq', ['433', '868', '915'], '915', None),
            ('cycle', 'NTP Boot', 'Apps.NTP_On_Boot', ['false', 'true'], 'false', None),
            ('head', 'SECURITY'),
            ('push', 'Set PIN', lambda: PinScreen('set')),
            ('cycle', 'Web Panel', 'Apps.NovaD1_Web', ['off', 'on'], 'off', _apply_web),
            ('head', 'ACTIONS'),
            ('action', 'Check Updates', 'update check'),
            ('action', 'Update Nova', 'pkg upgrade'),
            ('action', 'NTP Sync', 'ntp sync'),
            ('action', 'Web Info', 'novad1 web'),
            ('action', 'System Info', 'sysinfo'),
            ('action', 'Reboot', 'sreboot'),
        ]
        self.sel = self._step(0, 1)         # land on the first non-header row

    def _step(self, start, d):
        """Return the next selectable (non-head) row index from `start`, dir d."""
        n = len(self.rows)
        i = start
        for _ in range(n):
            if self.rows[i][0] != 'head':
                return i
            i = (i + d) % n
        return start

    def _rows_visible(self, c):
        return (c.h - _TOP) // _ROWH

    def _val(self, row):
        return _reg(row[2], row[4])

    def draw(self, c):
        rows = self._rows_visible(c)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + rows:
            self.top = self.sel - rows + 1
        for i in range(rows):
            idx = self.top + i
            if idx >= len(self.rows):
                break
            r = self.rows[idx]
            y = _TOP + i * _ROWH
            if r[0] == 'head':
                c.text(2, y, r[1][:14], 1)
                c.hline(2 + len(r[1]) * _ADV + 2, y + _FH // 2, c.w - (len(r[1]) * _ADV + 8), 1)
                continue
            inv = (idx == self.sel)
            if inv:
                c.fill_rect(0, y - 1, c.w, _ROWH, 1)
            tc = 0 if inv else 1
            c.text(7, y, r[1][:11], tc)
            if r[0] in ('push', 'action'):
                c.text(c.w - _ADV - 2, y, '>', tc)
            else:
                v = self._val(r)
                c.text(c.w - len(v) * _ADV - 2, y, v, tc)
        if self.top > 0:
            _scroll_tri(c, c.w - 5, _TOP, True)          # more settings above
        if self.top + rows < len(self.rows):
            _scroll_tri(c, c.w - 5, c.h - 4, False)      # more settings below

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.sel = self._step((self.sel + 1) % len(self.rows), 1)
        elif e == ev.ROT_CCW:
            self.sel = self._step((self.sel - 1) % len(self.rows), -1)
        elif e == ev.SELECT:
            r = self.rows[self.sel]
            if r[0] == 'push':
                return r[2]()
            if r[0] == 'action':
                return CommandScreen(r[1], r[2])
            vals = r[3]
            try:
                i = vals.index(self._val(r))
            except ValueError:
                i = 0
            nv = vals[(i + 1) % len(vals)]
            _save_reg(r[2], nv)
            if r[2] == 'Apps.NovaD1_HomeStyle':
                _mark_home_dirty()         # gallery<->menu applies live
            if r[5]:
                try:
                    r[5](nv)
                except Exception:
                    pass
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


def _settings_menu():
    return SettingsScreen()


def build_home(modules=None, style=None):
    """Home = an icon per enabled app + Settings. `modules` (key->present) greys
    out auto-undetected ones; homepage config (Apps.NovaD1_Home) picks/orders;
    Apps.NovaD1_HomeStyle = 'gallery' (default) | 'menu' picks the layout."""
    modules = modules or {}
    apps = _all_apps()                       # (key, label, factory) triples
    _load_cat_overrides()                    # user reassignments -> _app_category
    # Script-apps (installed) always show — the home config only picks/orders the
    # built-in apps, so a freshly installed app is never hidden by an old config.
    scripts = [a for a in apps if a[0].startswith('script_')]
    apps = [a for a in apps if not a[0].startswith('script_')]
    enabled = _home_keys()
    if enabled is not None:
        order = {k: i for i, k in enumerate(enabled)}
        apps = sorted([a for a in apps if a[0] in order], key=lambda a: order[a[0]])
    apps = apps + scripts
    triples = []
    for key, label, fac in apps:
        present = modules.get(key, True)
        triples.append((key, label, fac if present else None))
    triples.append(('settings', 'Settings', _settings_menu))
    if style is None:
        style = _reg('Apps.NovaD1_HomeStyle', 'folders')
    if style == 'menu':
        return Menu('Nova D1', [(l, f) for _k, l, f in triples])
    if style == 'folders':
        return _build_folder_home(triples)
    return IconGallery('Nova D1', triples)


def _build_folder_home(triples):
    """Group apps by category into folders — the top level shows a folder per
    category (Wireless / Sensors / Tools / System); opening one shows just that
    category's apps. Friendlier than one long ring of 18+ icons. Uncategorised or
    empty -> the flat gallery."""
    by_cat = {}
    for key, label, fac in triples:
        by_cat.setdefault(_app_category(key), []).append((key, label, fac))
    items = []
    for cat in _CATEGORIES:
        apps = by_cat.get(cat)
        if apps:
            items.append((_CAT_ICON.get(cat, 'app'),
                          '{} ({})'.format(cat, len(apps)), _mk_folder(cat, apps)))
    if len(items) < 2:
        return IconGallery('Nova D1', triples)
    return IconGallery('Nova D1', items)
