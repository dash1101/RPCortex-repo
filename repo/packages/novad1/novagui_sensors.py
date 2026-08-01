# Desc: Nova D1 sensor + utility app screens (LED / Battery / Environment / Clock).
# File: /Packages/NovaD1/novagui_sensors.py
#
# Split out of novagui (the monolith de-cluttering). These are self-contained real
# apps: they bind only to the novaui leaf (Screen/tokens/ev) + lazy hardware imports
# (novapower/novamods), never to novagui orchestration. novagui imports them back.
# See ARCHITECTURE.md. MicroPython-safe: no f-strings, .format() only.

from novaui import Screen, ev, _TOP, _ROWH, _ADV, _FH, _wrap, _scroll_tri, fit as _fit  # noqa


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
        self.msg = 'turn=pick Sel=set'
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
        _fit(c, 2, c.h - _FH, self.msg)

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(self.COLORS)
            self._apply()
            self.msg = 'turn=pick Sel=set'
            return None
        if e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(self.COLORS)
            self._apply()
            self.msg = 'turn=pick Sel=set'
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
            _fit(c, 2, _TOP + _ROWH, 'No battery detected')
            _fit(c, 2, _TOP + 2 * _ROWH, 'set the battery pin')
        else:
            pct = d.get('pct', 0)
            bw = c.w - 8
            c.rect(2, _TOP + _ROWH, bw, 11, 1)
            c.fill_rect(4, _TOP + _ROWH + 2, int((bw - 4) * pct / 100), 7, 1)
            c.text(2, _TOP + 2 * _ROWH + 2, '{}%   {:.2f} V'.format(pct, d.get('volts', 0)), 1)
            usb = d.get('usb')
            usbs = 'charging' if usb else ('on battery' if usb is not None else 'USB ?')
            c.text(2, _TOP + 3 * _ROWH + 2, usbs + ('  LOW' if d.get('low') else ''), 1)

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
            _fit(c, 2, _TOP + 2 * _ROWH, '(no DHT? check pin)')
        else:
            c.text(2, _TOP + _ROWH, 'Temp:  {} C'.format(self.t), 1)
            c.text(2, _TOP + 2 * _ROWH, 'Humid: {} %'.format(self.h), 1)
            if self.tmin is not None:
                c.text(2, _TOP + 3 * _ROWH + 2, 'min {}  max {}'.format(self.tmin, self.tmax), 1)

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


class ClockScreen(Screen):
    """A big clock (time + date) with a stopwatch. Turn to switch Clock <-> Stopwatch.
    Stopwatch: SELECT = start / stop / reset. A real Tools app (reads the RTC; the
    device shows local time, same source as the status-bar clock)."""
    def __init__(self):
        self.title = 'Clock'
        self.view = 0            # 0 = clock, 1 = stopwatch
        self.sw_ms = 0
        self.sw_run = False
        self._last_s = -1

    def _lt(self):
        # Apply System.TZ_Offset (whole hours) like the status-bar clock and
        # notifications do — the Clock app was showing raw RTC/UTC time.
        try:
            import utime
            from novacore import reg as _r
            try:
                off = int(_r('System.TZ_Offset', 0) or 0)
            except (TypeError, ValueError):
                off = 0
            return utime.localtime(utime.time() + off * 3600)
        except Exception:
            return (2026, 1, 1, 0, 0, 0, 0, 0)

    def _big(self, c, s):
        sc = 2
        x = max(0, (c.w - len(s) * _ADV * sc) // 2)
        c.text(x, _TOP + 4, s, 1, sc)
        return _TOP + 4 + _FH * sc

    def draw(self, c):
        if self.view == 0:
            t = self._lt()
            self._big(c, '{:02d}:{:02d}:{:02d}'.format(t[3], t[4], t[5]))
            days = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
            dow = days[t[6]] if 0 <= t[6] < 7 else ''
            ds = '{} {:04d}-{:02d}-{:02d}'.format(dow, t[0], t[1], t[2])
            c.text(max(0, (c.w - len(ds) * _ADV) // 2), _TOP + 4 + _FH * 2 + 5, ds, 1)
            c.text(2, c.h - _FH, 'turn: stopwatch', 1)
        else:
            cs = self.sw_ms // 10                    # centiseconds
            self._big(c, '{:02d}:{:02d}.{:1d}'.format(cs // 6000, (cs // 100) % 60, (cs // 10) % 10))
            foot = 'SEL stop' if self.sw_run else ('SEL reset  turn: clock' if self.sw_ms else 'SEL start  turn: clock')
            c.text(2, c.h - _FH, foot, 1)

    def tick(self, dt_ms=0):
        if self.view == 1:
            if self.sw_run:
                self.sw_ms += dt_ms or 16
                return True
            return False
        t = self._lt()                               # clock view: redraw on second change
        if t[5] != self._last_s:
            self._last_s = t[5]
            return True
        return False

    def on_event(self, e):
        if e in (ev.ROT_CW, ev.ROT_CCW):
            self.view ^= 1
            self._last_s = -1
            return None
        if e == ev.SELECT and self.view == 1:
            if self.sw_run:
                self.sw_run = False                  # stop
            elif self.sw_ms:
                self.sw_ms = 0                       # reset
            else:
                self.sw_run = True                   # start
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None
