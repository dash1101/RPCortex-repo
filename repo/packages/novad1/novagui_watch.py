# Desc: Nova D1 Radar screens — what the background observer has been hearing.
# File: /Packages/NovaD1/novagui_watch.py
#
# Three screens, deliberately shallow. The observer (novawatch) does the work in
# the background, so these only ever read a table that is already populated —
# nothing here scans, blocks or waits.
#
#   Radar     one line per device, strongest first. That is the whole screen.
#   Detail    SELECT on a device: who it is, since when, how strong, plus the
#             two actions worth having (track it, or name it).
#   Locate    a live meter you walk around with.
#
# The depth is one level down, not spread across the surface: the list stays a
# list. MicroPython-safe: no f-strings, .format() only.

from novaui import (Screen, ev, _TOP, _ROWH, _ADV, _FH, _SB_W, fit as _fit,
                    rounded_rect, scrollbar)  # noqa


def _age(ms):
    """'now' / '3m' / '2h' — a duration that fits in four characters.

    Clamped at both ends. ticks_ms wraps, and a record stamped either side of a
    wrap (or by a caller using a different clock) can produce a nonsense span;
    printing '495992h' next to a device is worse than admitting we do not know."""
    if ms is None:
        return '?'
    if ms < 0:
        return 'now'
    s = ms // 1000
    if s < 45:
        return 'now'
    if s < 3600:
        return '{}m'.format(s // 60)
    h = s // 3600
    return '{}h'.format(h) if h < 100 else '99h+' 


def _line(rec):
    """The one line a device gets in the list. Resolves the vendor on the way —
    identification is deferred until something is actually being shown, so a
    device that never opens Radar never loads the lookup tables.

    Name if it advertised one, else vendor, else the OUI prefix — never a guess.
    A randomised MAC says so, because 'unknown' would imply we failed to identify
    it when in fact there is nothing there to identify."""
    try:
        import novawatch
        novawatch.identify(rec)
    except Exception:
        pass
    nm = rec.get('name') or rec.get('ssid')
    if not nm:
        nm = rec.get('vendor')
    if not nm:
        if rec.get('random'):
            nm = '(random)'
        else:
            try:
                import novaoui
                nm = novaoui.prefix(rec['mac'])
            except Exception:
                nm = rec['mac'][:8]
    return nm[:13]


class RadarScreen(Screen):
    """Everything the observer has heard, strongest first."""
    def __init__(self):
        self.title = 'Radar'
        self.sel = 0
        self.top = 0
        self.mode = 0                 # 0 all, 1 BLE, 2 WiFi, 3 tagged
        self._n = -1

    MODES = (None, 'ble', 'wifi', None)
    MODE_NAME = ('all', 'BLE', 'WiFi', 'known')

    def _rows(self):
        """The devices, with a settings row pinned to the front.

        Radar's settings live here rather than in the global Settings menu: they
        only mean anything while you are looking at this screen. Same synthetic
        first-row pattern the WiFi list uses for '+ Add network', so it sits in a
        predictable place instead of behind a gesture."""
        import novawatch
        if self.mode == 3:
            k = novawatch.known()
            devs = [r for r in novawatch.devices() if r['mac'] in k]
        else:
            devs = novawatch.devices(kind=self.MODES[self.mode])
        return [None] + devs

    def tick(self, dt_ms=0):
        n = len(self._rows())
        if n != self._n:
            self._n = n
            return True
        return False

    def draw(self, c):
        import novawatch
        if novawatch.silenced():
            # Say so, rather than showing the last table as though it were live.
            # A stale list looks identical to a working one, which is exactly the
            # wrong impression to give on a screen about what is around you.
            _fit(c, 2, _TOP, 'Radios are OFF')
            _fit(c, 2, _TOP + _ROWH, 'Incognito is engaged,')
            _fit(c, 2, _TOP + 2 * _ROWH, 'so nothing is being')
            _fit(c, 2, _TOP + 3 * _ROWH, 'received.')
            _fit(c, 2, c.h - _FH, '{} last seen'.format(novawatch.count()))
            return
        rows = self._rows()
        avail = (c.h - _TOP - _FH) // _ROWH
        if not novawatch.enabled():
            _fit(c, 2, _TOP, 'Observer is OFF')
            _fit(c, 2, _TOP + _ROWH, 'It listens constantly,')
            _fit(c, 2, _TOP + 2 * _ROWH, 'which uses memory.')
            _fit(c, 2, _TOP + 3 * _ROWH, 'Turn on in settings.')
            _fit(c, 2, c.h - _FH, 'Sel = Radar settings')
            return
        if len(rows) <= 1:
            _fit(c, 2, _TOP, 'Listening...')
            _fit(c, 2, _TOP + _ROWH, 'nothing heard yet')
            _fit(c, 2, c.h - _FH, 'turn=filter: ' + self.MODE_NAME[self.mode])
            return
        if self.sel >= len(rows):
            self.sel = len(rows) - 1
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + avail:
            self.top = self.sel - avail + 1
        scrolls = len(rows) > avail
        right = c.w - (_SB_W + 1) if scrolls else c.w
        known = novawatch.known()
        for i in range(avail):
            idx = self.top + i
            if idx >= len(rows):
                break
            r = rows[idx]
            y = _TOP + i * _ROWH
            inv = (idx == self.sel)
            if inv:
                rounded_rect(c, 0, y - 1, right, _ROWH, 1)
            tc = 0 if inv else 1
            if r is None:
                _fit(c, 2, y, 'Radar settings', tc)
                c.text(right - _ADV - 2, y, '>', tc)
                continue
            mark = '*' if r['mac'] in known else (
                '!' if r.get('class') == 'tracker' else ' ')
            c.text(2, y, mark, tc)
            _fit(c, 2 + _ADV, y, _line(r), tc)
            rs = r.get('rssi')
            db = 'join' if rs is None else '{}'.format(rs)
            c.text(right - len(db) * _ADV - 2, y, db, tc)
        if scrolls:
            scrollbar(c, right + 1, _TOP, c.h - _TOP - _FH, self.top, avail, len(rows))
        _fit(c, 2, c.h - _FH, '{} {}  hold=filter'.format(
            len(rows) - 1, self.MODE_NAME[self.mode]))

    def on_event(self, e):
        rows = self._rows()
        if e == ev.ROT_CW:
            self.sel = min(self.sel + 1, max(0, len(rows) - 1))
        elif e == ev.ROT_CCW:
            self.sel = max(0, self.sel - 1)
        elif e == ev.SELECT and not __import__('novawatch').enabled():
            import novagui
            return novagui.SettingsScreen('Radar', novagui._rows_radar())
        elif e == ev.SELECT and rows and self.sel < len(rows):
            r = rows[self.sel]
            if r is None:
                import novagui
                return novagui.SettingsScreen('Radar', novagui._rows_radar())
            return DeviceScreen(r['mac'])
        elif e == ev.SELECT_HOLD:
            self.mode = (self.mode + 1) % 4      # cycle the filter
            self.sel = self.top = 0
            self._n = -1
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class DeviceScreen(Screen):
    """One device in full, plus the two things worth doing with it."""
    def __init__(self, mac):
        self.title = 'Device'
        self.mac = mac
        self.sel = 0
        self.msg = ''

    def _rec(self):
        import novawatch
        return novawatch.identify(novawatch.get(self.mac)) or {'mac': self.mac}

    def _actions(self):
        import novawatch
        tagged = self.mac in novawatch.known()
        return [('Locate', 'locate'), ('Forget' if tagged else 'Name it', 'tag')]

    def draw(self, c):
        import novawatch
        r = self._rec()
        y = _TOP
        _fit(c, 2, y, _line(r))
        y += _ROWH
        v = r.get('vendor')
        if r.get('random'):
            _fit(c, 2, y, 'randomised MAC')
        elif v:
            _fit(c, 2, y, v + (' ' + r['class'] if r.get('class') else ''))
        else:
            _fit(c, 2, y, r.get('mac', '')[:17])
        y += _ROWH
        now = novawatch._now()
        seen = _age(novawatch._elapsed(now, r.get('last', now)))
        held = _age(novawatch._elapsed(now, r.get('first', now)))
        rs = r.get('rssi')
        _fit(c, 2, y, ('joined  seen {}'.format(seen) if rs is None
                       else '{} dBm  seen {}'.format(rs, seen)))
        y += _ROWH
        _fit(c, 2, y, 'here {}  x{}'.format(held, r.get('count', 0)))
        y += _ROWH
        if self.msg:
            _fit(c, 2, y, self.msg)
        else:
            acts = self._actions()
            x = 2
            for i, (label, _k) in enumerate(acts):
                w = c.text_width(label, 1, True) + 6
                if i == self.sel:
                    rounded_rect(c, x, y - 1, w, _ROWH, 1)
                c.text(x + 3, y, label, 0 if i == self.sel else 1, 1, True)
                x += w + 3

    def on_event(self, e):
        import novawatch
        acts = self._actions()
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % len(acts)
            self.msg = ''
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % len(acts)
            self.msg = ''
        elif e in (ev.SELECT, ev.SELECT_HOLD):
            what = acts[self.sel][1]
            if what == 'locate':
                return LocateScreen(self.mac)
            if self.mac in novawatch.known():
                novawatch.untag(self.mac)
                self.msg = 'forgotten'
            else:
                return _name_screen(self.mac)
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


def _name_screen(mac):
    """Type a label with the on-screen keyboard, then tag the device with it."""
    from novagui_system import KeyboardScreen

    def done(text):
        import novawatch
        novawatch.tag(mac, text or mac)
        return 'back'
    import novawatch
    r = novawatch.get(mac) or {}
    return KeyboardScreen('Name', on_done=done, initial=(r.get('name') or '')[:12])


class LocateScreen(Screen):
    """Walk around with this. A single antenna cannot give a bearing, so it shows
    signal strength and which way it is MOVING — you do the triangulating with
    your feet, which is how every practical single-antenna locator works."""
    def __init__(self, mac):
        self.title = 'Locate'
        self.mac = mac
        import novawatch
        r = novawatch.get(mac) or {}
        self.tracker = novawatch.Tracker(mac, tx=r.get('tx'))
        self._last_count = -1

    def animating(self):
        return True

    def tick(self, dt_ms=0):
        import novawatch
        r = novawatch.get(self.mac)
        if r and r.get('count') != self._last_count:
            self._last_count = r.get('count')
            self.tracker.feed(r.get('rssi'))
            return True
        return False

    def draw(self, c):
        import novawatch
        if novawatch.silenced():
            _fit(c, 2, _TOP, 'Radios are OFF')
            _fit(c, 2, _TOP + _ROWH, 'Cannot locate while')
            _fit(c, 2, _TOP + 2 * _ROWH, 'incognito is engaged.')
            return
        t = self.tracker
        _fit(c, 2, _TOP, self._name())
        # the meter
        y = _TOP + _ROWH + 2
        bw = c.w - 8
        c.rect(4, y, bw, 11, 1)
        n = t.bars(20)
        if n:
            c.fill_rect(6, y + 2, int((bw - 4) * n / 20.0), 7, 1)
        y += 14
        if t.level is None:
            _fit(c, 4, y, 'listening...')
        else:
            _fit(c, 4, y, '{} dBm   {}'.format(int(t.level), t.hint()))
            m = t.metres()
            y += _ROWH
            _fit(c, 4, y, ('~{} m away'.format(m) if m is not None
                           else 'no range est.'))
        _fit(c, 2, c.h - _FH, 'walk around  BACK=done')

    def _name(self):
        import novawatch
        r = novawatch.get(self.mac)
        return _line(r) if r else self.mac[:13]

    def on_event(self, e):
        if e in (ev.BACK, ev.HOME):
            return e
        return None


class PresenceScreen(Screen):
    """The named devices, and whether they are here. This is the "is anyone home"
    view — the same thing a smart camera does when it recognises your phone."""
    def __init__(self):
        self.title = 'Presence'
        self.top = 0

    def tick(self, dt_ms=0):
        return True

    def draw(self, c):
        import novawatch
        rows = novawatch.presence()
        if not rows:
            _fit(c, 2, _TOP, 'No named devices.')
            _fit(c, 2, _TOP + _ROWH, 'Name one in Radar')
            _fit(c, 2, _TOP + 2 * _ROWH, 'to watch for it here.')
            return
        avail = (c.h - _TOP - _FH) // _ROWH
        for i in range(avail):
            idx = self.top + i
            if idx >= len(rows):
                break
            label, _mac, here, rssi = rows[idx]
            y = _TOP + i * _ROWH
            _fit(c, 2, y, label[:11])
            s = 'here' if here else 'away'
            if here and rssi is not None:
                s = '{} dBm'.format(rssi)
            c.text(c.w - c.text_width(s, 1, True) - 2, y, s, 1, 1, True)
        _fit(c, 2, c.h - _FH, '{} watched'.format(len(rows)))

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.top += 1
        elif e == ev.ROT_CCW:
            self.top = max(0, self.top - 1)
        elif e in (ev.BACK, ev.HOME):
            return e
        return None
