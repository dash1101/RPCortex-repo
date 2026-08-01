# Desc: Nova D1 RF / wireless app screens (Messages / GPS / NFC / IR / Sub-GHz / BLE / LoRa).
# File: /Packages/NovaD1/novagui_radios.py
#
# Split out of novagui (the monolith de-cluttering, round 2). These are the
# radio/peripheral app screens: each binds only to the novaui leaf (Screen /
# tokens / ev / _wrap) + novacore reg + LAZY hardware imports (novamsg / novair /
# novacc / novable / novamods / novanfc / novastore / nova), never to novagui
# orchestration. novagui imports the classes back; the small home-wiring
# factories (_ir_app / _ble_app / ...) stay there. See ARCHITECTURE.md.
# MicroPython-safe: no f-strings, .format() only.

from novaui import Screen, ev, _TOP, _ROWH, _ADV, _FH, _wrap, fit as _fit  # noqa
from novacore import reg as _reg  # noqa


class MessagesScreen(Screen):
    """LoRa messaging view — backed by the shared novamsg manager (same inbox the
    web panel uses). Shows the conversation; SELECT opens the on-screen keyboard to
    write a message, HOLD SELECT broadcasts a quick 'ping'. (Composing used to mean
    reaching for the web panel on a phone — the device can do it itself now.) The
    manager owns the radio + listens in the background, so messages arrive even off
    this screen."""
    def __init__(self):
        self.title = 'Messages'
        self.top = 0
        self._last = -1
        self._sent = None
        self._sent_ms = 0        # countdown; the status clears itself (see tick)

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
            _fit(c, 2, _TOP + _ROWH, 'check SX1276 wiring')
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
        _fit(c, 2, c.h - _FH, (self._sent or 'Sel=write  hold=ping') + enc)

    def tick(self, dt_ms=0):
        if self._sent_ms > 0:
            # 'sent' is a transient status, not a new footer. Left permanent it
            # replaces the 'Sel=write hold=ping' hint for the rest of the session,
            # which is the same stuck-activity-text problem reported before.
            self._sent_ms -= dt_ms
            if self._sent_ms <= 0:
                self._sent = None
                self._sent_ms = 0
                return True
        try:
            import novamsg
            n = len(novamsg.inbox())
        except Exception:
            n = 0
        if n != self._last:                      # redraw when the inbox changes
            self._last = n
            return True
        return False

    def _status(self, msg):
        self._sent = msg
        self._sent_ms = 2500
        self._last = -1                          # force a redraw with the new footer

    def _send(self, text):
        text = (text or '').strip()
        if not text:
            return False
        try:
            import novamsg
            novamsg.send(text)
            self._status('sent')
        except Exception:
            self._status('send failed')
        return True

    def _compose(self):
        from novagui_system import KeyboardScreen

        def done(txt):
            self._send(txt)
            return 'back'
        return KeyboardScreen('Message', on_done=done)

    def on_event(self, e):
        if e == ev.SELECT:
            return self._compose()
        if e == ev.SELECT_HOLD:
            try:
                import novamsg
                import novamesh
                novamsg.send('ping ' + str(novamesh.node_id()))
                self._status('ping sent')
            except Exception:
                self._status('ping failed')
            return None
        if e in (ev.BACK, ev.HOME):
            return e
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
            import novaboard
            tx = novaboard.pin('gps_tx', 17)
            rx = novaboard.pin('gps_rx', 18)
            self.u = machine.UART(1, baudrate=9600, tx=machine.Pin(tx), rx=machine.Pin(rx))
        except Exception as e:
            self.err = str(e)[:16]

    def draw(self, c):
        if self.u is None:
            _fit(c, 2, _TOP, 'GPS: ' + (self.err or 'n/a'))
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
        foot = self.msg or ('Sel=save' if self.fix else '')
        _fit(c, 2, c.h - _FH, foot)

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
            foot = 'Sel=save'
        else:
            foot = ''
        _fit(c, 2, c.h - _FH, foot)

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
        _fit(c, 2, _TOP + 2 * _ROWH, self.msg)
        _fit(c, 2, c.h - _FH, '' if self.state == 'done' else 'BACK=cancel')

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
        _fit(c, 2, c.h - _FH, self.msg or ('Sel=' + self.fire_label))

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
        self.msg = 'point remote+Sel'
        self._cap = False

    def draw(self, c):
        c.text(2, _TOP, 'Record IR', 1)
        _fit(c, 2, _TOP + _ROWH, self.msg)
        _fit(c, 2, c.h - _FH, 'Sel=rec')

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
        _fit(c, 2, c.h - _FH, self.msg or 'Sel=send')

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
        _fit(c, 2, c.h - _FH, self.msg or 'Sel=open Home=del')

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
        _fit(c, 2, _TOP + 2 * _ROWH, self.msg)
        _fit(c, 2, c.h - _FH, '' if self.state == 'done' else 'BACK=cancel')

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
        _fit(c, 2, _TOP + 2 * _ROWH, self.msg)
        _fit(c, 2, c.h - _FH, 'BACK=stop')

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
        _fit(c, 2, c.h - _FH, self.msg or 'Sel=run')

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


class WardriveScreen(Screen):
    """Wardriving — a rolling WiFi survey. Scans every few seconds, tags each new AP
    with the live GPS fix + time, dedups by BSSID, and appends a WiGLE-compatible CSV
    (SD if present, else flash with the storage guard). SELECT starts/pauses; the scan
    runs cooperatively in tick() so the UI/services stay live. BACK stops + closes the
    file."""
    def __init__(self):
        self.title = 'Wardrive'
        self.running = False
        self.msg = 'SELECT = start'
        self.sess = None
        self.path = None
        self.on_sd = False
        self._acc = 0
        self._interval = 4000        # ms between scans
        self._gpsu = None
        self._gbuf = b''
        self.fix = None              # (lat, lon)
        self.alt = None
        self._err = None
        self._open_gps()

    def _open_gps(self):
        try:
            import machine
            import novaboard
            tx = novaboard.pin('gps_tx', 0)
            rx = novaboard.pin('gps_rx', 1)
            self._gpsu = machine.UART(1, baudrate=9600, tx=machine.Pin(tx), rx=machine.Pin(rx))
        except Exception:
            self._gpsu = None        # GPS optional — survey still logs APs without coords

    def _ts(self):
        try:
            import utime
            t = utime.localtime()
            return '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
                t[0], t[1], t[2], t[3], t[4], t[5])
        except Exception:
            return ''

    def _start(self):
        import novawardrive as wd
        base, on_sd = wd.log_dir()
        ok, why = wd.can_write(on_sd)
        if not ok:
            self.msg = why[:16]
            return
        try:
            import uos
            try:
                uos.mkdir(base)
            except OSError:
                pass
            self.path = base + '/wardrive.csv'
            newfile = True
            try:
                uos.stat(self.path)
                newfile = False
            except OSError:
                pass
            f = open(self.path, 'a')
            if newfile:
                f.write(wd.wigle_header())
            f.close()
        except Exception as e:
            self.msg = 'log err'
            self._err = str(e)[:16]
            return
        self.sess = wd.Session()
        self.on_sd = on_sd
        self.running = True
        self._acc = self._interval           # scan immediately on start
        self.msg = 'scanning...'

    def _pause(self):
        self.running = False
        self.msg = 'paused'

    def _do_scan(self):
        import novawardrive as wd
        aps = wd.scan_now()
        lat = self.fix[0] if self.fix else None
        lon = self.fix[1] if self.fix else None
        rows = self.sess.add(aps, self._ts(), lat, lon, self.alt)
        if rows:
            # flash guard mid-run: stop cleanly if the disk hit the block level
            ok, why = wd.can_write(self.on_sd)
            if not ok:
                self._pause()
                self.msg = 'FULL-stopped'
                return
            try:
                f = open(self.path, 'a')
                for r in rows:
                    f.write(r)
                f.close()
            except Exception:
                self._pause()
                self.msg = 'write err'
                return
        self.msg = '{} APs / {} pass'.format(self.sess.total, self.sess.scans)

    def _pump_gps(self):
        if self._gpsu is None:
            return
        try:
            import novagui_radios as _self   # reuse the shared NMEA decoder
            while self._gpsu.any():
                d = self._gpsu.read()
                if not d:
                    break
                self._gbuf += d
                while b'\n' in self._gbuf:
                    line, self._gbuf = self._gbuf.split(b'\n', 1)
                    s = line.decode('ascii', 'ignore')
                    f = s.split(',')
                    if 'GGA' in s and len(f) > 9 and f[6] not in ('', '0'):
                        self.fix = (float(_nmea_dec(f[2], f[3])),
                                    float(_nmea_dec(f[4], f[5])))
                        self.alt = f[9]
        except Exception:
            pass

    def tick(self, dt_ms=0):
        if not self.running:
            return False
        self._pump_gps()
        self._acc += dt_ms
        if self._acc >= self._interval:
            self._acc = 0
            self._do_scan()
            return True
        return False

    def draw(self, c):
        y = _TOP
        c.text(2, y, 'Wardrive ' + ('REC' if self.running else 'idle'), 1); y += _ROWH
        if self.sess is not None:
            c.text(2, y, 'APs: {}'.format(self.sess.total), 1); y += _ROWH
        loc = 'SD' if self.on_sd else 'flash'
        gps = 'GPS ok' if self.fix else 'no fix'
        c.text(2, y, loc + '  ' + gps, 1); y += _ROWH
        _fit(c, 2, c.h - _FH, self.msg or '')

    def on_event(self, e):
        if e == ev.SELECT:
            if self.running:
                self._pause()
            else:
                self._start()
            return None
        if e in (ev.BACK, ev.HOME):
            self.running = False
            return e
        return None
