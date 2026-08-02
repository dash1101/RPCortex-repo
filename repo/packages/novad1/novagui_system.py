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

from novaui import (Screen, ev, _TOP, _ROWH, _ADV, _FH, _wrap, fit as _fit,
                    rounded_rect)  # noqa
import novacore as _novacore  # noqa
from novacore import reg as _reg, save_reg as _save_reg  # noqa


class WiFiScreen(Screen):
    """Functional WiFi app: show status, scan, connect to a saved network."""
    help = ('OK = scan',
            'hold OK = add a net',
            'on a net: OK = join',
            'hold OK = forget it')
    def __init__(self):
        self.title = 'WiFi'
        self.nets = []          # list of (ssid, rssi, saved)
        self.sel = 0
        self.top = 0
        self.msg = 'OK = scan'
        self._pending = None    # 'scan' | ('connect', ssid) | ('connectpw', ssid, pw)
        self._ask_pw = None     # ssid awaiting a typed password

    def _status_line(self):
        try:
            import net
            st = net.status()
            if st.get('connected'):
                return 'Online: ' + str(st.get('ssid', '?'))[:7]
            return 'Offline'
        except Exception:
            return 'net n/a'

    def _rows(self):
        """The scan results with a synthetic 'add manually' row on the front, so a
        hidden network — or one that is simply out of range right now — can still
        be set up without dropping to the shell."""
        return [(None, 0, False)] + list(self.nets)

    def draw(self, c):
        c.text(2, _TOP, self._status_line()[:16], 1)
        if self.nets:
            entries = self._rows()
            rows = (c.h - _TOP - _ROWH) // _ROWH + 1   # the hint row is now free
            if self.sel < self.top:
                self.top = self.sel
            elif self.sel >= self.top + rows:
                self.top = self.sel - rows + 1
            for i in range(rows):
                idx = self.top + i
                if idx >= len(entries):
                    break
                ssid, _rssi, saved = entries[idx]
                y = _TOP + _ROWH + i * _ROWH
                row = '+ Add network' if ssid is None else '{}{}'.format(
                    '*' if saved else ' ', ssid[:16])
                if idx == self.sel:
                    rounded_rect(c, 0, y - 1, c.w, _ROWH, 1)
                    _fit(c, 2, y, row, 0)
                else:
                    _fit(c, 2, y, row, 1)
            # No hint row: the controls are in `help`, and the list gets the space.
            # Leaving it here would have drawn over the extra entry the list can
            # now show, which is what removing the OTHER hint had just bought.
        else:
            _fit(c, 2, _TOP + _ROWH, self.msg)

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
        if isinstance(self._pending, tuple) and self._pending[0] == 'connectpw':
            _, ssid, pw = self._pending
            self._pending = None
            self.msg = 'Connecting...'
            self._do_connect(ssid, pw)
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
            # A scan allocates a tuple per AP plus two bytes objects each, all at
            # once. On a device that has been up a while that burst is exactly
            # what fails -- and it used to surface as 'scan err: memory allo',
            # a truncated errno with nothing the user could do about it. Reclaim
            # and retry once: the shell's command cache is usually the only thing
            # standing in the way, so the second attempt normally succeeds.
            ok, res = _novacore.retry_oom(wlan.scan)
            if not ok:
                self.msg = _novacore.oom_message()
                self.nets = []
                return
            res = res or []
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
            # Say something actionable. 'scan err: memory allo' told the user
            # nothing; a plain reason plus what to do about it is the minimum.
            self.msg = _novacore.oom_message() if _novacore.is_oom(e) \
                else 'Scan failed - retry'
        finally:
            novawifi.resume()

    def _do_connect(self, ssid, password=None):
        try:
            import net
            ok = False
            if password is not None:
                # Explicit password from the on-screen keyboard: save it so the
                # network joins now AND reconnects on its own next time.
                try:
                    net.add_network(ssid, password)
                except Exception:
                    pass
                try:
                    ok = net.connect(ssid, password)
                except TypeError:
                    ok = net.connect_saved(ssid)
            else:
                try:
                    ok = net.connect_saved(ssid)
                except TypeError:
                    ok = net.connect_saved()
            if ok:
                self.msg = 'Connected ' + ssid[:10]
            elif password is None:
                self.msg = 'Need password'
                self._ask_pw = ssid          # SELECT opens the keyboard
                return
            else:
                self.msg = 'Wrong password?'
        except Exception as e:
            self.msg = 'conn err: ' + str(e)[:12]
        self.nets = []          # back to the status view

    def _add_screen(self):
        """Type an SSID, then a password — for a hidden network, or one that is
        simply not in range at the moment."""
        def got_ssid(name):
            name = (name or '').strip()
            if name:
                self._ask_pw = name
                self.msg = 'Password for ' + name[:9]
            return 'back'
        return KeyboardScreen('Network', on_done=got_ssid)

    def _forget(self, ssid):
        """Remove a saved network. Deliberately does not touch the radio — this is
        a file edit, so it works while the radios are locked."""
        try:
            import net
            net.forget_saved(ssid)
            self.msg = 'Forgot ' + ssid[:9]
        except Exception:
            self.msg = 'Could not forget'
        self._pending = 'scan'

    def _password_screen(self, ssid):
        """The on-screen keyboard, wired to join `ssid` with what gets typed."""
        def done(pw):
            self._pending = ('connectpw', ssid, pw)
            return 'back'
        return KeyboardScreen('Password', on_done=done, secret=True)

    def on_event(self, e):
        if not self.nets:
            if e == ev.SELECT:
                if self._ask_pw:                 # a join asked for a password
                    ssid = self._ask_pw
                    self._ask_pw = None
                    return self._password_screen(ssid)
                self.msg = 'Scanning...'
                self._pending = 'scan'
                return None
            if e == ev.SELECT_HOLD:
                return self._add_screen()        # works with nothing in range
            if e in (ev.BACK, ev.HOME):
                return e
            return None
        entries = self._rows()
        if e == ev.ROT_CW:
            self.sel = min(self.sel + 1, len(entries) - 1)
        elif e == ev.ROT_CCW:
            self.sel = max(self.sel - 1, 0)
        elif e == ev.SELECT_HOLD:
            ssid, _r, saved = entries[self.sel]
            if ssid is not None and saved:
                self._forget(ssid)
            return None
        elif e == ev.SELECT:
            ssid, _r, saved = entries[self.sel]
            if ssid is None:
                return self._add_screen()
            if saved:
                self.msg = 'Connecting...'
                self._pending = ('connect', ssid)
                return None
            # Not saved: go STRAIGHT to the keyboard. This used to say
            # 'Not saved (use shell)', which made a locked network unjoinable from
            # the device even though the keyboard existed.
            return self._password_screen(ssid)
        elif e == ev.BACK:
            self.nets = []       # back to status, not out of the app
            return None
        elif e == ev.HOME:
            return 'home'
        return None


class TimeScreen(Screen):
    """Set the hardware clock (hour/minute). Select switches field, turn adjusts."""
    help = ('turn = change value',
            'OK = next field',
            'hold OK = save')
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
    help = ('turn = scroll',
            'OK = clear all')
    def __init__(self):
        self.title = 'Alerts'
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
        # Opt out of the runner's global HOME escape while VERIFYING. A lock that
        # HOME walks out of is not a lock. In 'set' mode HOME is an ordinary way
        # to abandon the edit, so the flag is off.
        self.modal = (mode == 'verify')

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


class KeyboardScreen(Screen):
    """On-screen keyboard driven entirely by the rotary encoder.

    Turn = move through the key grid, SELECT = type the highlighted key, HOLD
    SELECT = accept (the OK shortcut), BACK = delete (and leaves when the buffer is
    empty). The bottom row carries SHIFT / SPACE / DEL / OK, so every function is
    reachable with the encoder and one button — all the hardware there is.

    on_done(text) receives the finished string; on_cancel() if abandoned.
    """
    # 10 columns wide to match the panel: letters, then punctuation, then the digits
    # on their own row (there are exactly 10, so they line up one-per-column).
    ROWS = (
        'abcdefghij',
        'klmnopqrst',
        'uvwxyz.-_@',
        '0123456789',
    )
    ACTIONS = ('SHF', 'SPACE', 'DEL', 'OK')
    HOLD_MS = 600                 # SELECT held this long = OK

    def __init__(self, title='Enter text', on_done=None, on_cancel=None,
                 secret=False, initial=''):
        self.title = title
        self.text = initial
        self.sel = 0
        self.shift = False
        self.secret = secret            # mask the buffer (passwords)
        self._done = on_done
        self._cancel = on_cancel
        self._keys = self._build()
        self._blink = 0                 # caret phase
        self._caret = True

    def _build(self):
        keys = []
        for r, row in enumerate(self.ROWS):
            for col, ch in enumerate(row):
                keys.append((r, col, ch))
        for col, a in enumerate(self.ACTIONS):
            keys.append((len(self.ROWS), col, a))
        return keys

    def _cell(self, c):
        """(cell_w, cell_h, x0, y0) for the key grid."""
        cols = max(len(r) for r in self.ROWS)
        gw = c.w // cols
        gh = max(7, (c.h - _TOP - _FH - 2) // (len(self.ROWS) + 1))
        return gw, gh, 0, _TOP + _FH + 2

    def animating(self):
        return True                     # keep ticking so the caret blinks

    def tick(self, dt_ms=0):
        self._blink += dt_ms or 40
        if self._blink >= 450:
            self._blink = 0
            self._caret = not self._caret
            return True
        return False

    def _space_key(self, c, x, y, w, h, inv):
        """The space bar drawn as the standard 'open box' mark rather than the word
        SPACE, which is what a real keyboard shows."""
        col = 0 if inv else 1
        mid = y + h // 2
        x0, x1 = x + 3, x + w - 4
        c.vline(x0, mid - 1, 3, col)
        c.vline(x1, mid - 1, 3, col)
        c.hline(x0, mid + 2, x1 - x0 + 1, col)

    def draw(self, c):
        # buffer line, masked for secrets, with a blinking caret
        shown = ('*' * len(self.text)) if self.secret else self.text
        shown = shown[-19:]
        _fit(c, 2, _TOP, shown)
        if self._caret:
            cx = 2 + c.text_width(shown)
            c.vline(cx, _TOP, _FH, 1)
        gw, gh, x0, y0 = self._cell(c)
        nact = len(self.ACTIONS)
        aw = c.w // nact                      # wider cells for the action row
        for i, (r, col, ch) in enumerate(self._keys):
            action_row = (r == len(self.ROWS))
            cw = aw if action_row else gw
            x = x0 + col * cw
            y = y0 + r * gh
            inv = (i == self.sel)
            if inv:
                rounded_rect(c, x, y - 1, cw - 1, gh, 1)
            if ch == 'SPACE':
                self._space_key(c, x, y, cw, gh, inv)
                continue
            label = ch.upper() if (len(ch) == 1 and self.shift) else ch
            c.text(x + 1, y, label, 0 if inv else 1)

    def _type(self, ch):
        if len(self.text) < 63:
            self.text += ch.upper() if self.shift else ch

    def on_event(self, e):
        n = len(self._keys)
        if e == ev.ROT_CW:
            self.sel = (self.sel + 1) % n
        elif e == ev.ROT_CCW:
            self.sel = (self.sel - 1) % n
        elif e == ev.SELECT_HOLD:
            # Holding SELECT accepts, wherever the cursor is — the shortcut for OK.
            if self._done:
                return self._done(self.text) or 'back'
            return 'back'
        elif e == ev.SELECT:
            ch = self._keys[self.sel][2]
            if ch == 'SHF':
                self.shift = not self.shift
            elif ch == 'SPACE':
                self._type(' ')
            elif ch == 'DEL':
                self.text = self.text[:-1]
            elif ch == 'OK':
                if self._done:
                    return self._done(self.text) or 'back'
                return 'back'
            else:
                self._type(ch)
        elif e == ev.BACK:
            if self.text:
                self.text = self.text[:-1]      # BACK deletes while there's text
                return None
            if self._cancel:
                self._cancel()
            return 'back'
        elif e == ev.HOME:
            return 'home'
        return None


class TZScreen(Screen):
    """Set the UTC offset in whole hours.

    A cycle row would have meant tapping through 27 values to get from -12 to +14,
    so this is a dedicated screen: turn to adjust, SELECT to save. It writes
    System.TZ_Offset, the same key the OS shell's `settings` uses and the one the
    status-bar clock, the notification timestamps and the Clock app all read — so
    setting it here moves every clock on the device at once.

    Titled 'Timezone' rather than 'UTC Offset' because the longer string does not
    fit the status bar once the clock and status icons have taken their share, and
    a title that has to be truncated to fit is one that should have been shorter."""
    help = ('turn = adjust',
            'OK = save')
    title = 'Timezone'

    # The real range of civil offsets. Whole hours only: nothing on this device
    # reads a fractional offset, so offering 5:30 would be a lie.
    LO = -12
    HI = 14

    def __init__(self):
        self.saved = False
        try:
            self.off = int(_reg('System.TZ_Offset', 0) or 0)
        except Exception:
            self.off = 0
        if self.off < self.LO or self.off > self.HI:
            self.off = 0

    def _label(self):
        return 'UTC{}{}'.format('+' if self.off >= 0 else '-', abs(self.off))

    def draw(self, c):
        _fit(c, 2, _TOP, 'hours from UTC')
        lbl = self._label()
        c.text(max(0, (c.w - c.text_width(lbl, 2)) // 2), c.h // 2 - _FH, lbl, 1, 2)
        # 19 characters, because the panel is 20 wide and the old hint ran off the
        # edge mid-word -- it read 'OK = s', which is worse than no hint at all.

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.off = self.off + 1 if self.off < self.HI else self.LO
            self.saved = False
        elif e == ev.ROT_CCW:
            self.off = self.off - 1 if self.off > self.LO else self.HI
            self.saved = False
        elif e == ev.SELECT:
            _save_reg('System.TZ_Offset', str(self.off))
            self.saved = True
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class VersionsScreen(Screen):
    """Everything that has a version, in one place.

    These numbers were scattered: the OS version in Sys Check, the build id only
    in the Updates screen, the package version nowhere in the UI at all, and the
    firmware version only from the shell. When something behaves oddly the first
    question is always "which of these am I actually running", and it should not
    take four screens to answer."""
    help = ('turn = scroll')
    title = 'Versions'

    def __init__(self):
        self.top = 0
        self.rows = self._read()

    def _read(self):
        rows = []
        try:
            rows.append(('OS', str(_reg('Settings.Version', '?'))))
            rows.append(('Build', str(_reg('System.Build', '?'))))
            stage = str(_reg('System.Stage', '') or 'unknown')
            rows.append(('Stage', stage))
            chan = str(_reg('Settings.Update_Channel', '') or '').strip().lower()
            if chan not in ('stable', 'beta'):
                # Match the implicit choice the update check makes, rather than
                # showing a blank for the very common "never set it" case.
                chan = 'beta*' if stage.lower() in (
                    'pre-release', 'prerelease', 'beta', 'alpha', 'rc') else 'stable*'
            rows.append(('Channel', chan))
        except Exception:
            pass
        try:
            with open('/Packages/NovaD1/package.cfg') as f:
                for ln in f.read().split('\n'):
                    if ln.startswith('pkg.ver'):
                        rows.append(('NovaD1', ln.split(':', 1)[1].strip()))
                        break
        except Exception:
            rows.append(('NovaD1', '?'))
        try:
            import sys as _s
            # Just the number. CPython's sys.version is a paragraph ('3.13.5
            # (main, ...') and MicroPython's carries a build suffix; neither fits
            # beside a label on a 20-column panel.
            v = _s.version.split()[0].split(';')[0].strip() if hasattr(_s, 'version') else '?'
            rows.append(('Python', v[:10]))
        except Exception:
            pass
        try:
            import uos
            u = uos.uname()
            rows.append(('Firmware', str(u.release)))
            rows.append(('Board', str(u.machine)[:14]))
        except Exception:
            pass
        try:
            import novaboard
            rows.append(('Profile', str(novaboard.board())))
        except Exception:
            pass
        return rows

    def _visible(self, c):
        return max(1, (c.h - _TOP) // _ROWH)

    def draw(self, c):
        vis = self._visible(c)
        n = len(self.rows)
        if self.top > max(0, n - vis):
            self.top = max(0, n - vis)
        for i in range(vis):
            idx = self.top + i
            if idx >= n:
                break
            label, val = self.rows[idx]
            y = _TOP + i * _ROWH
            c.text(2, y, label, 1)
            # Trim the value from the LEFT if it cannot fit beside its label. For a
            # version string the tail is the part that distinguishes one build from
            # another, and letting it collide with the label instead produced a row
            # that read as neither.
            avail = c.w - 4 - c.text_width(label) - 4
            vw = c.text_width(val)
            while val and vw > avail:
                val = val[1:]
                vw = c.text_width(val)
            c.text(max(2, c.w - vw - 2), y, val, 1)

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.top += 1
        elif e == ev.ROT_CCW:
            self.top = max(0, self.top - 1)
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class ScreenLock(Screen):
    """The lock for a device with no code set.

    Locking used to do nothing at all when there was no PIN or password —
    `_power_lock` returned None and the menu simply stayed put, which reads as a
    broken button. But a device with no code has nothing to verify, so a PIN pad
    would be theatre. What it can honestly offer is a screen lock: the panel is
    covered, stray presses in a pocket do nothing, and a deliberate gesture gets
    you back. That is the same guarantee a phone gives with no passcode set.

    The gesture is a HOLD of SELECT rather than a tap, for the same reason the
    shutdown wake is a hold: a single press is exactly what a pocket produces."""
    help = ('hold OK = unlock',)
    fullscreen = True
    title = 'Locked'

    # Ordinary input must not dismiss this, or it is not a lock. The runner reads
    # this flag and drops events instead of acting on them.
    manual_wake = True
    # Also opt out of the runner's global HOME escape: a codeless lock still has
    # to be a lock, and HOME is the one button guaranteed to reach every screen.
    modal = True
    HOLD_MS = 600

    def __init__(self):
        self._held = 0

    def draw(self, c):
        c.clear(0)
        # A padlock, drawn from the same primitives as the icons: a shackle arc
        # approximated by two verticals and a top bar, over a solid body.
        bw, bh = 22, 16
        bx = (c.w - bw) // 2
        by = c.h // 2 - 4
        c.rect(bx, by, bw, bh, 1)
        # Shackle: two uprights joined by a bar. The bar has to START on the left
        # upright and END on the right one — drawn inset by a pixel it left a gap
        # at each corner and the lock read as a bracket resting on a box.
        sx0, sx1 = bx + 5, bx + bw - 6
        c.vline(sx0, by - 7, 7, 1)
        c.vline(sx1, by - 7, 7, 1)
        c.hline(sx0, by - 7, sx1 - sx0 + 1, 1)
        c.fill_rect(bx + bw // 2 - 1, by + 5, 3, 6, 1)
        hint = 'hold SELECT'
        c.text(max(0, (c.w - c.text_width(hint)) // 2), c.h - _FH - 2, hint, 1)

    def on_event(self, e):
        # SELECT_HOLD is emitted by novainput once the button passes its hold
        # threshold; a plain SELECT (which fires on release) is ignored on purpose.
        if e == ev.SELECT_HOLD:
            return 'back'
        return None


def lock_screen(mode='verify'):
    """The lock the device is configured for: a typed PASSWORD when one is set
    (Apps.NovaD1_Pass), else the 6-digit PIN. Both are clearable from the serial
    shell, so neither can strand the device.

    With NO code set and mode='verify', this is a codeless screen lock rather than
    nothing at all — see ScreenLock. mode='set' still returns a real editor,
    because that path exists precisely to create a code."""
    from novacore import reg as _r
    kind = str(_r('Apps.NovaD1_Lock_Kind', 'pin')).lower()
    if mode == 'verify' and not lock_is_set():
        return ScreenLock()
    if kind == 'password':
        return PasswordScreen(mode)
    return PinScreen(mode)


def lock_is_set():
    """True if either lock is configured. Type 'none' means no lock whatever is
    still stored, matching novagui.lock_is_set."""
    from novacore import reg as _r
    kind = str(_r('Apps.NovaD1_Lock_Kind', 'pin')).lower()
    if kind == 'none':
        return False
    if kind == 'password':
        return bool(_r('Apps.NovaD1_Pass', ''))
    return bool(_r('Apps.NovaD1_PIN', ''))


class PasswordScreen(Screen):
    """Password lock — the alternative to the 6-digit PIN, so security isn't capped
    at 6 digits. Reuses the on-screen keyboard for entry (masked). mode='set'
    stores a new password; mode='verify' gates the UI until it matches.
    RECOVERY: `reg set Apps.NovaD1_Pass ""` from the serial shell always clears it."""
    fullscreen = True

    def __init__(self, mode='verify'):
        self.title = 'Password'
        self.mode = mode
        # Opt out of the runner's global HOME escape while VERIFYING. A lock that
        # HOME walks out of is not a lock. In 'set' mode HOME is an ordinary way
        # to abandon the edit, so the flag is off.
        self.modal = (mode == 'verify')

        self.msg = ''
        self.next = None
        self._kb = None

    def _keyboard(self):
        if self._kb is None:
            self._kb = KeyboardScreen(
                'Set password' if self.mode == 'set' else 'Password',
                on_done=self._submit, secret=True)
        return self._kb

    def _submit(self, text):
        from novacore import reg as _r, save_reg as _sr
        if self.mode == 'set':
            _sr('Apps.NovaD1_Pass', text)
            _sr('Apps.NovaD1_Lock_Kind', 'password' if text else 'pin')
            self.msg = 'Password set' if text else 'Password cleared'
            self.next = 'back'
            return 'back'
        if text == str(_r('Apps.NovaD1_Pass', '')):
            self.next = 'back'
            return 'back'
        self.msg = 'Wrong password'
        self._kb = None                 # start a fresh entry
        return None

    def draw(self, c):
        self._keyboard().draw(c)
        if self.msg:
            _fit(c, 2, c.h - _FH, self.msg)

    def tick(self, dt_ms=0):
        return self._keyboard().tick(dt_ms)

    def animating(self):
        return True

    def on_event(self, e):
        if self.mode == 'verify' and e in (ev.BACK, ev.HOME):
            return None                 # a verify lock can't be escaped
        r = self._keyboard().on_event(e)
        if r == 'back' and self.mode == 'verify':
            from novacore import reg as _r
            if not _r('Apps.NovaD1_Pass', ''):
                return 'back'           # cleared from the shell -> release
            return None
        return r
