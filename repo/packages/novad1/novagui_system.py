# Desc: Nova D1 system app screens (WiFi / Set Time / System Check / Notifications / PIN).
# File: /Packages/NovaD1/novagui_system.py
#
# Split out of novagui (the monolith de-cluttering, round 2). These are the
# leaf-safe system screens: each binds only to the novaui leaf (Screen / tokens /
# ev / _wrap) + novacore reg + LAZY hardware imports (net / novawifi / novamods /
# novalog / novanotify / machine), never to novagui orchestration. novagui imports
# them back. The settings/management screens that DO reach the runner (Display,
# ManageApps, Settings, AppStore, Command) stay in novagui by design. See
# ARCHITECTURE.md. MicroPython-safe: no f-strings, .format() only.

from novaui import Screen, ev, _TOP, _ROWH, _ADV, _FH, _wrap  # noqa
from novacore import reg as _reg, save_reg as _save_reg  # noqa


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
