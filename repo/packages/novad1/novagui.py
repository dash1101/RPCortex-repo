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

import novaicons
import novacanvas  # noqa  (kept for symmetry; canvas is passed in)
# The UI leaf: Screen base, layout tokens, shared helpers, the input `ev` re-export.
# Screens (here + the split-out novagui_* modules) + installed apps bind to novaui.
from novaui import (ev, _ADV, _FH, _BARH, _TOP, _ROWH, _SB_W, spinner,
                    Screen, Menu, _wrap, _scroll_tri, rounded_rect, scrollbar,
                    fit as _fit)
# RF / wireless app screens live in novagui_radios (the monolith split); the
# home-wiring factories below still reference them by name.
from novagui_radios import (MessagesScreen, GPSScreen, NFCScreen, NfcSaveScreen,
                            CodeListScreen, IRCaptureScreen, IRSignalsScreen,
                            IRFilesScreen, SubGhzFireScreen, BlePingScreen,
                            ButtonGridScreen, WardriveScreen)
# System app screens (leaf-safe subset) live in novagui_system (the monolith
# split); novagui re-exports them so novagui.PinScreen etc. still resolve.
from novagui_system import (WiFiScreen, TimeScreen, SystemCheckScreen,
                            NotificationsScreen, PinScreen, KeyboardScreen,
                            PasswordScreen, lock_screen, lock_is_set)


import novacore as _novacore
from novacore import reg as _reg


from novacore import save_reg as _save_reg


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


def _apply_stealth(val):
    """Toggling Incognito from settings must DO it, not just store a flag — kill
    every radio when switched on, release the latch when switched off."""
    try:
        import novastealth
        if str(val).lower() == 'on':
            novastealth.kill_all()
        else:
            novastealth.restore()
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
    # Rounded shell: the corner pixels are dropped so it reads as a battery with
    # soft corners instead of a hard rectangle.
    c.hline(x + 1, y, 9, 1)
    c.hline(x + 1, y + 5, 9, 1)
    c.vline(x, y + 1, 4, 1)
    c.vline(x + 10, y + 1, 4, 1)
    c.fill_rect(x + 11, y + 2, 1, 2, 1)         # nub
    if low:
        c.pixel(x + 5, y + 2, 1)                # '!' when low (rest empty)
        c.pixel(x + 5, y + 4, 1)
        return
    fillw = (pct * 9) // 100
    if fillw > 0:
        c.fill_rect(x + 1, y + 1, fillw, 4, 1)


def _stealth_mark(c, phase):
    """Incognito indicator — the extreme bottom-left corner, pulsing between a dot
    and a small plus so it reads as active suppression. Kept to 3px and hard against
    the corner so it sits in the margin rather than over content."""
    x, y = 1, c.h - 2
    c.pixel(x, y, 1)
    if phase >= 1:
        c.hline(x - 1, y, 3, 1)
    if phase >= 2:
        c.vline(x, y - 1, 2, 1)

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
    # Right-aligned clock, then (battery)(usb)(wifi) leftward, then the title fills
    # what's left — all measured from the font so a font swap can't clip anything.
    # Battery + USB icons appear ONLY when power info says they're present (no
    # lying icon).
    #
    # 128px against five icons is genuinely tight, so the bar spends every pixel it
    # can on the title: both the clock and the title are drawn NARROW (proportional
    # spacing — same glyphs, ~25% less width) and the icons sit on a 2px gap rather
    # than 3. That is still only ~52px of title, which is why screen titles are
    # short by design; test_screenfit asserts every one of them fits the WORST case
    # (bell + battery + USB + wifi all showing) so nothing can lose a letter again.
    w = c.w
    tstr = state.get('time', '--:--')
    tw = c.text_width(tstr, 1, True)
    tx = w - tw
    c.text(tx, 1, tstr, 1, 1, True)
    x = tx - 2
    pwr = state.get('power') or {}
    if pwr.get('usb'):
        # On USB: show the USB icon (mains power, battery level irrelevant).
        x -= 7
        _usb(c, x, 1)
        x -= 2
        if pwr.get('have'):                 # charging with a sensed pack: show both
            x -= 12
            _battery(c, x, 2, pwr.get('pct', 0), pwr.get('low'))
            x -= 2
    elif pwr.get('have'):
        x -= 12
        _battery(c, x, 2, pwr.get('pct', 0), pwr.get('low'))
        x -= 2
    else:
        # Running, but NOT on USB and with no battery sense pin — it must be on
        # battery (VSYS) with an unknown level, so show an EMPTY battery rather
        # than nothing, which read as "no power source".
        x -= 12
        _battery(c, x, 2, 0, False)
        x -= 2
    x -= 8
    _wifi(c, x, 2, state.get('wifi', False))
    if state.get('saving'):                 # SD backup in progress -> save icon
        x -= 9
        _disk(c, x, 1)
    if state.get('notify'):                 # unread notifications -> bell
        x -= 9
        _bell(c, x, 1)
    title = state.get('title', 'Nova D1')
    avail = title_budget(c, x)
    while title and c.text_width(title, 1, True) > avail:
        title = title[:-1]
    c.text(2, 1, title, 1, 1, True)
    c.hline(0, _BARH, w, 1)


def title_budget(c, x=None):
    """Pixels a status-bar title may use. With no x, the worst PERSISTENT case:
    clock + battery + USB + wifi + the unread-notification bell. The SD-save icon
    is left out on purpose — it appears only during a backup, so budgeting for it
    would shorten every title on the device to buy nothing."""
    if x is None:
        x = c.w - c.text_width('88:88', 1, True) - 2 - 7 - 2 - 12 - 2 - 8 - 9
    return max(0, x - 4)


# --- screens ----------------------------------------------------------------
# Screen base, Menu, _wrap, _scroll_tri + the layout tokens now live in novaui.py
# (the UI leaf), imported above. Everything below is Nova-specific screens +
# the runner, which import those from novaui.

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
            # Snap the slide before launching. Mid-animation the CENTRED ICON is the
            # item at sel_f (where the slide is) while sel is already the target —
            # so a select during the slide launched something the screen wasn't
            # showing yet. Snapping makes the visual and the action agree.
            self.sel_f = float(self.sel)
            fac = self.items[self.sel][2]
            return fac() if fac else None
        elif e == ev.BACK:
            return 'back'
        return None


class TextScreen(Screen):
    """Read-only text with word-wrap + vertical scroll. Long lines wrap to the panel
    width so nothing runs off the edge; the encoder scrolls, with up/down hints."""
    def __init__(self, title, lines):
        self.title = title
        self.src = list(lines)
        self.top = 0
        self._wrapped = None
        self._wrap_w = -1

    def _lines(self, c):
        # Wrap once per width (re-wrap only if the canvas width changes), so a long
        # line becomes several rows instead of being clipped at the edge.
        if self._wrapped is None or self._wrap_w != c.w:
            cols = max(1, (c.w - 4) // _ADV)
            out = []
            for ln in self.src:
                out.extend(_wrap(str(ln), cols))
            self._wrapped = out or ['']
            self._wrap_w = c.w
        return self._wrapped

    def _rows(self, c):
        return max(1, (c.h - _TOP) // _ROWH)

    def draw(self, c):
        lines = self._lines(c)
        rows = self._rows(c)
        if self.top > max(0, len(lines) - rows):     # clamp (also fixes over-scroll)
            self.top = max(0, len(lines) - rows)
        for i in range(rows):
            idx = self.top + i
            if idx >= len(lines):
                break
            c.text(2, _TOP + i * _ROWH, lines[idx], 1)
        if self.top > 0:
            _scroll_tri(c, c.w - 6, _TOP, True)          # more above
        if self.top + rows < len(lines):
            _scroll_tri(c, c.w - 6, c.h - 4, False)      # more below

    def on_event(self, e):
        n = len(self._wrapped) if self._wrapped else len(self.src)
        if e == ev.ROT_CW:
            self.top = min(self.top + 1, max(0, n - 1))  # draw() re-clamps to fit
        elif e == ev.ROT_CCW:
            self.top = max(0, self.top - 1)
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
        c.text(4, c.h - _FH, 'BACK = cancel' if not self.done else '', 1)

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
        self.lines = ['Select = run']
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


class SplashScreen(Screen):
    """Animated RPCortex / Nova D1 boot reveal. Auto-advances; any key skips."""
    fullscreen = True
    # Short on purpose: the splash is the first thing between power-on and a usable
    # UI, so it must read as snappy. It plays in FULL (the opening frame is no
    # longer swallowed by panel init) — it just plays quickly.
    DUR = 850

    def __init__(self):
        self.title = 'Nova D1'
        self.t = 0.0
        self.next = None
        self._first = True

    def draw(self, c):
        import novasplash
        novasplash.draw(c, self.t if self.t < 1 else 1.0)

    def tick(self, dt_ms=0):
        if self.t >= 1.0:
            self.next = 'back'
            return False
        if self._first:
            # Panel init + the first full-frame push can take a while; the first
            # tick's dt swallows all of it. Render the opening frame (t=0) here and
            # start the clock now, so the animation plays in FULL instead of jumping
            # past the opening — without padding boot time (init already happened).
            self._first = False
            return True
        self.t += min(dt_ms or 16, 80) / float(self.DUR)   # cap dt so a stall can't skip
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


def _ir_app():
    return IRFilesScreen()


def _subghz_app():
    return CodeListScreen('Sub-GHz', 'subghz', lambda t: None, fire_label='TX',
                          fire_screen=lambda n, t: SubGhzFireScreen(n, t))


def _ble_app():
    return Menu('BLE', [
        ('Scan nearby', lambda: ModuleTestScreen('bt', 'Bluetooth')),
        ('Ping iPhone', lambda: BlePingScreen('apple')),
        ('Ping Android', lambda: BlePingScreen('android')),
    ])


from novagui_sensors import BatteryScreen, EnvironmentScreen, ClockScreen

def _lora_tx_app():
    return CodeListScreen('LoRa TX', 'lora', _lora_fire, fire_label='send')


def _lora_fire(t):
    import novamsg
    novamsg.send(t.strip())


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
        _fit(c, 2, c.h - _FH, self.msg or 'Sel=open')

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
        self._stealth_on = False     # incognito -> pulse the corner mark
        self._stealth_ph = -1        # last drawn pulse phase
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
        # Incognito indicator: drawn LAST so it sits above whatever the screen
        # painted, in the bottom-left where content is thinnest. Pulses so it reads
        # as live suppression rather than a static badge.
        if self._stealth_on:
            _stealth_mark(c, (now // 400) % 3)
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
        # HOLD HOME is a global escape: it opens the power screen from ANY screen,
        # no matter what is on top or what state it's in — so lock / shutdown /
        # reboot are always one gesture away in an emergency.
        if e == ev.HOME_HOLD:
            if not isinstance(self.stack[-1], Menu) or self.stack[-1].title != 'Power':
                self.stack.append(_power_menu())
            return True
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
        # Physical stealth kill switch (if a killsw pin is wired): a press engages
        # incognito immediately, from any screen. Cheap — poll_edge caches its Pin
        # and no-ops when no switch is configured.
        if not isinstance(self.stack[-1], StealthSplashScreen):
            try:
                import novastealth
                if novastealth.poll_edge():
                    self._apply(StealthSplashScreen())
                    dirty = True
            except Exception:
                pass
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
        # Track incognito for the corner mark; while it's on, keep repainting so the
        # pulse actually animates.
        try:
            import novastealth
            on = novastealth.active()
        except Exception:
            on = False
        if on != self._stealth_on:
            self._stealth_on = on
            dirty = True
        elif on:
            ph = (now // 400) % 3
            if ph != self._stealth_ph:
                self._stealth_ph = ph
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
                and lock_is_set()
                and idle >= (off_s + lock_s) * 1000):
            self._lock_scr = lock_screen('verify')
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
    return lock_screen('verify') if lock_is_set() else None


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


class RebootScreen(Screen):
    """Hard reboot from the UI. Running 'sreboot' through the shell deferred the
    reset until the async loop unwound — and the GUI service runs inside that loop,
    so it never happened and the screen just printed '(done)'. This paints a notice,
    lets one frame land, then resets the chip directly."""
    title = 'Reboot'
    fullscreen = True

    def __init__(self):
        self._n = 0

    def draw(self, c):
        c.clear(0)
        a = 'Rebooting'
        c.text((c.w - c.text_width(a, 2)) // 2, c.h // 2 - _FH, a, 1, 2, True)

    def tick(self, dt_ms=0):
        self._n += 1
        if self._n < 3:                 # let the notice actually render first
            return True
        try:
            from RPCortex import close_session_log
            close_session_log()
        except Exception:
            pass
        try:
            import regedit
            regedit.save('Settings.Startup', '0')     # clean-shutdown sentinel
        except Exception:
            pass
        try:
            import machine
            machine.reset()             # hard reset — works from inside the loop
        except Exception:
            pass
        return False


class ShutdownScreen(Screen):
    """A safe power-down. There's no true power-off on the Pico, so this kills every
    radio (stealth) and darkens the panel; any button reboots. Serial stays alive."""
    title = 'Shutdown'

    def __init__(self):
        self._done = False

    def tick(self, dt_ms=0):
        if not self._done:
            self._done = True
            try:
                import novastealth
                novastealth.kill_all()
            except Exception:
                pass
            return True
        return False

    def draw(self, c):
        c.clear(0)
        a = 'Powered down'
        b = 'press to reboot'
        c.text((c.w - len(a) * _ADV) // 2, c.h // 2 - _FH, a, 1)
        c.text((c.w - len(b) * _ADV) // 2, c.h // 2 + 2, b, 1)

    def on_event(self, e):
        if e in (ev.SELECT, ev.BACK, ev.HOME, ev.ROT_CW, ev.ROT_CCW):
            return RebootScreen()
        return None


class StealthSplashScreen(Screen):
    """Engages incognito — kills every radio — with a full-screen confirmation and a
    notification, then drops back home. Shown whether stealth is triggered from the
    menu, a shortcut, or the physical kill switch."""
    title = 'Incognito'

    def __init__(self):
        self._done = False
        self._t = 0

    def tick(self, dt_ms=0):
        if not self._done:
            self._done = True
            try:
                import novastealth
                novastealth.kill_all()
            except Exception:
                pass
            try:
                import novanotify
                novanotify.notify('Incognito ON - radios off')
            except Exception:
                pass
            return True
        self._t += dt_ms
        if self._t > 1600:                 # auto-return home after ~1.6 s
            self.next = 'home'
        return False

    def draw(self, c):
        c.clear(0)
        a = 'STEALTH'                       # scale 2 = 112px, fits the 128px panel
        c.text((c.w - len(a) * _ADV * 2) // 2, c.h // 2 - _FH * 2, a, 1, 2)
        b = 'all radios off'
        c.text((c.w - len(b) * _ADV) // 2, c.h // 2 + 6, b, 1)

    def on_event(self, e):
        if e in (ev.BACK, ev.HOME, ev.SELECT):
            return 'home'
        return None


def _power_menu():
    # Lock / Reboot / Shutdown / Reload, plus Incognito, Sleep and Exit. Reload
    # restarts the GUI service so it re-reads the pin config (apply a 'd1 pins'
    # change without a full reboot); Reboot reloads the whole OS.
    return Menu('Power', [
        ('Lock', _power_lock),
        ('Incognito', StealthSplashScreen),
        ('Reload', lambda: CommandScreen('Reload', 'novad1 refresh')),
        ('Reboot', RebootScreen),
        ('Shutdown', ShutdownScreen),
        ('Sleep', _power_sleep),
        ('Exit to shell', _power_exit),
    ])


def _blink_display():
    """Turn the panel off and on again — a common 'my screen is glitchy' fix, one tap."""
    if _active_ui is not None:
        try:
            d = _disp()
            if d is not None:
                d.power(False)
                import utime
                utime.sleep_ms(400)
                d.power(True)
                d.invalidate()          # force a full repaint after the blink
        except Exception:
            pass
    return None


def _keyboard_demo():
    """Try the on-screen keyboard standalone — the same widget WiFi uses for
    passwords. Typing OK shows what was entered."""
    def done(txt):
        return TextScreen('Typed', [txt or '(nothing)'])
    return KeyboardScreen('Keyboard', on_done=done)


def _update_status():
    """What's installed right now — OS build and the Nova D1 package version."""
    lines = []
    try:
        import RPCortex as _R
        lines.append('OS  ' + str(getattr(_R, 'OS_VERSION', '?')))
    except Exception:
        lines.append('OS  ?')
    try:
        import buildinfo
        lines.append('    build ' + str(getattr(buildinfo, 'BUILD', '?')))
        lines.append('    ' + str(getattr(buildinfo, 'STAGE', '')))
    except Exception:
        pass
    try:
        with open('/Packages/NovaD1/package.cfg') as f:
            for ln in f.read().split('\n'):
                if ln.startswith('pkg.ver'):
                    lines.append('Nova D1  ' + ln.split(':', 1)[1].strip())
                    break
    except Exception:
        lines.append('Nova D1  ?')
    return TextScreen('Installed', lines)


def _os_manifest_url():
    """The OTA manifest for the channel this device tracks (stable vs beta)."""
    from novacore import reg as _r
    beta = str(_r('Settings.Update_Channel', '')).strip().lower() == 'beta'
    return ('https://rpc.novalabs.app/releases/'
            + ('latest-dev.json' if beta else 'latest.json'))


def _pkg_version(name='NovaD1'):
    try:
        with open('/Packages/' + name + '/package.cfg') as f:
            for ln in f.read().split('\n'):
                if ln.startswith('pkg.ver'):
                    return ln.split(':', 1)[1].strip()
    except Exception:
        pass
    return '?'


_FETCH_TMP = '/Vela/nova/fetch.tmp'    # module-level so tests can point it elsewhere


def _ensure_dir(path):
    """Create the parent directories of `path`. Ignores 'already exists'."""
    import uos
    parts = path.strip('/').split('/')[:-1]
    cur = ''
    for seg in parts:
        cur = cur + '/' + seg
        try:
            uos.mkdir(cur)
        except Exception:
            pass                      # exists, or the FS says no — the open reports it


def _fetch_json(url, tmp=None):
    """Fetch a JSON document without ever holding the body in RAM.

    net.wget(dest=...) streams straight to flash in 512-byte chunks; the
    return-the-body form has to hold the whole document as one contiguous
    object. That matters more than the size suggests: it lands immediately after
    a TLS handshake has taken a 16.7 KB block, in a heap that never compacts, so
    the package index (~6 KB) was competing for contiguous space at the worst
    possible moment. Reading it back from the file costs a second pass over
    flash and no large allocation at all.

    The temp file is always removed, including on failure.

    The parent directory is created first. /Vela/nova exists only once something
    has touched the code store, so a device where Settings -> Updates is opened
    before Scripts would otherwise fail with ENOENT — a working update check
    broken by the very change meant to make it more reliable. The old code read
    into memory and touched no filesystem at all, so this is new exposure."""
    import json
    import net
    import gc
    tmp = tmp or _FETCH_TMP
    _ensure_dir(tmp)
    try:
        net.wget(url, dest=tmp, verbose=False)
        gc.collect()
        with open(tmp, 'r') as f:
            return json.load(f)
    finally:
        try:
            import uos
            uos.remove(tmp)
        except Exception:
            pass


_PKG_UPDATE_CMD = 'novad1 selfupdate -y'


def _cache_bust():
    try:
        import utime
        return utime.ticks_ms()
    except Exception:
        return 0


def _vtuple(v):
    """'v1.2.3' / '0.72.0' -> (1, 2, 3). Unparseable parts sort as 0."""
    out = []
    for part in str(v or '').lstrip('vV').split('.'):
        n = ''
        for ch in part:
            if ch.isdigit():
                n += ch
            else:
                break
        out.append(int(n) if n else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def _newer(available, installed):
    """True when `available` is a LATER version than `installed`.

    Compared numerically, not as strings. A plain `!=` also fires when the index
    is OLDER than what is installed, which offers a downgrade as if it were an
    update; and '0.9.0' > '0.72.0' lexically, which is simply wrong."""
    if not available or available == '?':
        return False
    if not installed or installed == '?':
        return True
    return _vtuple(available) > _vtuple(installed)


class UpdatesScreen(Screen):
    """A real update view instead of a shell dump: it fetches the manifests itself
    and renders what's installed vs what's available, with one action per component.
    Turn to pick a row, SELECT to act."""
    title = 'Updates'

    def __init__(self):
        self.rows = []
        self.sel = 0
        self.state = 'idle'      # idle | checking | done
        self._spin = 0
        self._frames = 0
        self.os_new = None       # (version, build, notes) when an OS update exists
        self.pkg_new = None      # (version) when a package update exists
        self.err = ''
        self._gen = None         # the in-flight check (see _check_steps)
        self._status = 'Checking...'

    # ---- data -------------------------------------------------------------
    def _cur_os(self):
        v = b = '?'
        try:
            from novacore import reg as _r
            v = _r('Settings.Version', '?')
            b = _r('System.Build', '?')
        except Exception:
            pass
        return v, b

    def _check_steps(self):
        """Fetch both manifests, as a GENERATOR that yields a status between each
        one. Two HTTPS fetches back to back is a long stall, and the GUI shares its
        event loop with the shell and the background services — running them in one
        blocking call froze all of it and left the spinner motionless, which is the
        opposite of what a spinner is for. Yielding between them lets the loop turn.

        Each fetch is still atomic (net.wget is synchronous), so this reduces the
        stall to one request rather than removing it. Any failure just shows a
        message instead of dumping a traceback."""
        self.err = ''
        try:
            import net
            if not net.status().get('connected'):
                self.err = 'No WiFi'
                return
        except Exception:
            self.err = 'No network'
            return

        yield 'Checking OS...'
        try:
            m = _fetch_json(_os_manifest_url())
            cv, cb = self._cur_os()
            lv, lb = m.get('version', '?'), str(m.get('build', ''))
            if _newer(lv, cv) or (lb and lb != str(cb)):
                self.os_new = (lv, lb, m.get('notes', ''))
        except Exception as e:
            self.err = _novacore.oom_message() if _novacore.is_oom(e) \
                else 'OS check failed'

        yield 'Checking app...'
        try:
            # A cache-buster on the URL: raw.githubusercontent serves the
            # /main/ path from a CDN that can hold a stale copy for minutes
            # after a push, which looks exactly like "no update available".
            idx = _fetch_json(
                'https://raw.githubusercontent.com/dash1101/RPCortex-repo'
                '/main/repo/index.json?t=' + str(_cache_bust()))
            for p in idx.get('packages', ()):
                if p.get('name') == 'NovaD1':
                    if _newer(p.get('ver'), _pkg_version()):
                        self.pkg_new = p.get('ver')
                    break
        except Exception as e:
            if not self.err:
                self.err = _novacore.oom_message() if _novacore.is_oom(e) \
                    else 'App check failed'

    def _build_rows(self):
        """Build the display rows.

        The important distinction here is "checked, and you are current" versus
        "could not check". Both used to render as 'up to date', with the reason
        appended as the LAST row — below the six that fit — so a failed check
        looked exactly like a successful one and the explanation was off-screen.
        That is why an available update could be reported as up to date."""
        cv, cb = self._cur_os()
        failed = bool(self.err)
        rows = []
        if failed:
            rows.append(('t', '! ' + self.err))      # first, not last
        rows.append(('t', 'OS   ' + str(cv)))
        rows.append(('t', '     build ' + str(cb)))
        if self.os_new:
            rows.append(('a', '-> ' + self.os_new[0] + ' b' + self.os_new[1],
                         'safeboot update online -y'))
        else:
            rows.append(('t', '     ' + ('not checked' if failed else 'up to date')))
        rows.append(('t', 'App  ' + _pkg_version()))
        if self.pkg_new:
            rows.append(('a', '-> ' + str(self.pkg_new), _PKG_UPDATE_CMD))
        else:
            rows.append(('t', '     ' + ('not checked' if failed else 'up to date')))
        rows.append(('a', 'Check again', None))
        self.rows = rows
        self.sel = next((i for i, r in enumerate(rows) if r[0] == 'a'), 0)

    # ---- screen -----------------------------------------------------------
    def animating(self):
        return self.state == 'checking'

    def tick(self, dt_ms=0):
        if self.state == 'idle':
            self.state = 'checking'
            self._frames = 0
            self._gen = None
            return True
        if self.state == 'checking':
            self._spin += 1
            self._frames += 1
            if self._frames < 2:
                return True          # paint the spinner before the first fetch
            if self._gen is None:
                self._gen = self._check_steps()
            try:
                self._status = next(self._gen) or self._status
            except StopIteration:
                self._gen = None
                self._build_rows()
                self.state = 'done'
            except Exception:
                self._gen = None
                if not self.err:
                    self.err = 'Check failed'
                self._build_rows()
                self.state = 'done'
            return True
        return False

    def draw(self, c):
        if self.state != 'done':
            _fit(c, 2, _TOP + _ROWH, self._status)
            spinner(c, c.w - 8, c.h - 8, self._spin)
            return
        rows = (c.h - _TOP) // _ROWH
        top = max(0, min(self.sel - rows + 1, len(self.rows) - rows)) if len(self.rows) > rows else 0
        for i in range(rows):
            idx = top + i
            if idx >= len(self.rows):
                break
            kind = self.rows[idx][0]
            label = self.rows[idx][1]
            y = _TOP + i * _ROWH
            if kind == 'a' and idx == self.sel:
                rounded_rect(c, 0, y - 1, c.w, _ROWH, 1)
                _fit(c, 3, y, label, 0)
            else:
                _fit(c, 3, y, label)

    def on_event(self, e):
        acts = [i for i, r in enumerate(self.rows) if r[0] == 'a']
        if not acts:
            if e in (ev.BACK, ev.HOME):
                return e
            return None
        if e == ev.ROT_CW:
            nxt = [i for i in acts if i > self.sel]
            self.sel = nxt[0] if nxt else acts[0]
        elif e == ev.ROT_CCW:
            prv = [i for i in acts if i < self.sel]
            self.sel = prv[-1] if prv else acts[-1]
        elif e == ev.SELECT:
            row = self.rows[self.sel]
            cmd = row[2] if len(row) > 2 else None
            if cmd is None:                     # 'Check again'
                self.state = 'idle'
                self.os_new = self.pkg_new = None
                return None
            return CommandScreen('Updating', cmd)
        elif e in (ev.BACK, ev.HOME):
            return e
        return None

def _updates_menu():
    """Updates, split by what is actually being updated — the OS and the Nova D1
    app suite are separate things on separate channels. Both run through safeboot
    so the download gets a full heap, and -y so nothing waits on a keyboard that
    the panel doesn't have."""
    return Menu('Updates', [
        ('Installed', _update_status),
        ('Check for updates', lambda: CommandScreen('Check', 'update check')),
        ('Update RPCortex OS', lambda: CommandScreen('OS', 'safeboot update online -y')),
        ('Update Nova D1 app', lambda: CommandScreen('Nova D1', 'safeboot pkg upgrade -y')),
        ('Update channel', lambda: CommandScreen('Channel', 'update channel')),
    ])


def _troubleshoot_menu():
    """Recovery actions one tap away — the things you'd otherwise drop to the shell
    for when something's misbehaving."""
    return Menu('Repair', [
        ('Reconnect WiFi', lambda: CommandScreen('WiFi', 'wifi autoconnect')),
        ('WiFi status', lambda: CommandScreen('WiFi', 'wifi status')),
        ('Blink display', _blink_display),
        ('Reload pins', lambda: CommandScreen('Reload', 'novad1 refresh')),
        ('Restart GUI', lambda: CommandScreen('GUI', 'novad1 service restart')),
        ('Free memory', lambda: CommandScreen('Free RAM', 'defrag')),
        ('I2C scan', lambda: CommandScreen('I2C', 'novad1 scan')),
        ('Reboot device', RebootScreen),
    ])


def _commands_menu():
    """Curated read-only / safe shell commands surfaced in the GUI, grouped. Anything
    that reconfigures hardware (pins) or is destructive is deliberately left to the
    shell — this is for status + quick actions, moving the GUI toward TUI parity."""
    return Menu('Commands', [
        ('System info', lambda: CommandScreen('sysinfo', 'sysinfo')),
        ('Nova status', lambda: CommandScreen('status', 'novad1 status')),
        ('Memory', lambda: CommandScreen('meminfo', 'meminfo')),
        ('Contiguous RAM', lambda: CommandScreen('defrag', 'defrag')),
        ('Storage', lambda: CommandScreen('df', 'df')),
        ('Uptime', lambda: CommandScreen('uptime', 'uptime')),
        ('Pins', lambda: CommandScreen('pins', 'novad1 pins')),
        ('WiFi status', lambda: CommandScreen('wifi', 'wifi status')),
        ('Incognito status', lambda: CommandScreen('stealth', 'novad1 incognito status')),
        ('Nova logs', _logs_screen),
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
_CATEGORIES = ('Wireless', 'Sensors', 'Tools', 'System', 'Testing')
_APP_CAT = {
    'pn532': 'Wireless', 'bt': 'Wireless', 'cc1101': 'Wireless', 'sx1276': 'Wireless',
    'wifi': 'Wireless', 'ir': 'Wireless', 'msg': 'Wireless', 'wardrive': 'Wireless',
    'gps': 'Sensors', 'dht11': 'Sensors', 'battery': 'Sensors',
    'scripts': 'Tools', 'notes': 'Tools', 'logs': 'Tools', 'clock': 'Tools',
    'store': 'Tools', 'cmds': 'Tools',
    'check': 'System', 'power': 'System', 'settings': 'System', 'diag': 'System',
    'fix': 'System',
    'kbd': 'Testing',
    'radar': 'Wireless', 'presence': 'Wireless',
}
# A representative icon per category (reuses an app icon so folders look distinct).
_CAT_ICON = {'Wireless': 'bt', 'Sensors': 'gps', 'Tools': 'tools',
             'System': 'settings', 'Testing': 'kbd'}

# Modules that are pure hardware probes (no real 'app') — folded into Diagnostics
# instead of cluttering the home.
# 'led' is here rather than being its own app: the board has no addressable
# NeoPixel any more, so a colour-picker screen controls nothing. The onboard
# LED is driven by notifications (novanotify._led_alert) instead.
_DIAG_ONLY = ('buzzer', 'vibration', 'ibutton', 'sdcard', 'led')


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


def _py_apps():
    """Installed kind:py apps (from the 'pyapps' store) as HOME apps — full Nova-UI apps
    (not button grids). Each file defines app() -> Screen via the novaapps loader, which
    binds it to novaui (never novagui internals). TITLE/CATEGORY are optional."""
    out = []
    try:
        import novastore
        import novaapps
        for name in novastore.list_codes('pyapps'):
            src = novastore.read_code('pyapps', name) or ''
            fac, meta = novaapps.load_py_app(src)
            if fac is None:
                continue                              # doesn't compile / no app() -> skip
            key = 'pyapp_' + name
            _SCRIPT_CATS[key] = meta.get('category') or 'Tools'
            label = (meta.get('title') or name.rsplit('.', 1)[0])[:12]
            out.append((key, label, fac))             # fac() -> a fresh Screen
    except Exception:
        pass
    return out


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


def _radar_app():
    from novagui_watch import RadarScreen
    return RadarScreen()


def _presence_app():
    from novagui_watch import PresenceScreen
    return PresenceScreen()


def _diag_app():
    """Diagnostics: run any module's hardware self-test (absorbs the old per-module
    test icons, and keeps every module reachable for bring-up)."""
    import novamods
    items = []
    for k, label, _fn in novamods.MODULES:
        if k == 'ir_tx':
            continue
        items.append((label, _mk_test(k, label)))
    return Menu('Hardware', items)


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
        self.msg = 'Sel=install'
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
            return
        if not self.apps:
            c.text(2, _TOP + _ROWH, '(no apps found)', 1)
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
        elif k == 'dht11':
            apps.append((k, 'Climate', EnvironmentScreen))   # live temp/humidity
        elif k == 'battery':
            apps.append((k, 'Battery', BatteryScreen))   # live %, voltage, charging
        elif k in _DIAG_ONLY:
            continue                                    # -> Diagnostics app
        else:
            apps.append((k, l, _mk_test(k, l)))
    apps.append(('diag', 'Hardware', _diag_app))
    apps.append(('kbd', 'Keyboard', _keyboard_demo))           # rotary text entry
    apps.append(('fix', 'Repair', _troubleshoot_menu))         # recovery actions
    apps.append(('cmds', 'Commands', _commands_menu))          # curated shell commands
    apps.append(('store', 'App Store', AppStoreScreen))   # browse + install apps
    apps.append(('wifi', 'WiFi', WiFiScreen))
    apps.append(('wardrive', 'Wardrive', WardriveScreen))
    apps.append(('radar', 'Radar', _radar_app))          # what the observer heard
    apps.append(('presence', 'Presence', _presence_app))  # named devices, here or not
    apps.append(('msg', 'Messages', MessagesScreen))
    apps.append(('notes', 'Alerts', NotificationsScreen))
    apps.append(('check', 'Sys Check', SystemCheckScreen))
    apps.append(('logs', 'Logs', _logs_screen))
    apps.append(('scripts', 'Scripts', ScriptsScreen))
    apps.append(('clock', 'Clock', ClockScreen))          # time + date + stopwatch
    apps.append(('power', 'Power', _power_menu))
    apps.extend(_script_apps())              # installed button-grid script-apps -> home
    apps.extend(_py_apps())                  # installed kind:py apps -> home
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


def _fmt_capture(out):
    """Captured shell text -> wrapped display lines (ANSI stripped, blanks dropped)."""
    out = _strip_ansi(out or '')
    lines = []
    cols = (128 - 3) // _ADV
    for ln in out.split('\n'):
        ln = ln.rstrip('\r')
        if ln == '':
            continue
        lines.extend(_wrap(ln, cols))
    return lines


def _run_capture(cmd):
    """Run an OS shell command, return its output as wrapped display lines."""
    import sys
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
    if lp is None or not hasattr(lp, '_run_line'):
        return ['shell n/a']
    out = ''
    # Use the OS's own capture buffer FIRST: on MicroPython reassigning
    # sys.stdout does not reliably redirect the shell's output, so the old
    # StringIO path captured nothing and every command looked like '(done)'.
    try:
        import RPCortex as _R
        prev = _R.begin_capture()
        try:
            lp._run_line(cmd)
        finally:
            out = _R.end_capture(prev) or ''
    except Exception:
        out = ''
    if out.strip():
        return _fmt_capture(out)
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
    lines = _fmt_capture(out)
    if lines:
        return lines[:60]
    # A command that printed nothing used to show a bare '(done)', which says
    # nothing about what happened. Report the state the command was about instead.
    return _silent_result(cmd)


def _silent_result(cmd):
    """Meaningful output for a command that printed nothing, so the screen never
    just says '(done)'."""
    c = (cmd or '').strip().lower()
    try:
        if c.startswith('wifi'):
            import novawifi
            st = novawifi.status() if hasattr(novawifi, 'status') else None
            if isinstance(st, dict) and st.get('ip'):
                return ['Connected', st.get('ssid', ''), st.get('ip', '')]
            return ['Not connected', 'no WiFi link']
        if c.startswith('freeup') or c.startswith('gc'):
            import gc
            gc.collect()
            return ['Memory freed', '{} KB free'.format(gc.mem_free() // 1024)]
        if c.startswith('novad1 refresh') or c.startswith('novad1 service'):
            return ['GUI service', 'restarted']
        if c.startswith('update check') or c.startswith('update'):
            # 'update check' prints nothing when already current — say so, and show
            # what's installed, instead of a bare '(done)'.
            try:
                import RPCortex as _R
                v = getattr(_R, 'OS_VERSION', '?')
                b = ''
                try:
                    import buildinfo
                    b = getattr(buildinfo, 'BUILD', '')
                except Exception:
                    pass
                return ['Up to date', '{} {}'.format(v, b).strip(),
                        '(no newer build)']
            except Exception:
                return ['Up to date', '(no newer build)']
        if c.startswith('ntp'):
            try:
                import utime
                from novacore import reg as _r
                try:
                    off = int(_r('System.TZ_Offset', 0) or 0)
                except (TypeError, ValueError):
                    off = 0
                t = utime.localtime(utime.time() + off * 3600)
                return ['Clock synced',
                        '{:04d}-{:02d}-{:02d}'.format(t[0], t[1], t[2]),
                        '{:02d}:{:02d}:{:02d}'.format(t[3], t[4], t[5])]
            except Exception:
                return ['Clock synced']
    except Exception:
        pass
    return ['Done - no output']


class CommandScreen(Screen):
    """Runs an OS command, then shows its scrollable output.

    The command is deliberately NOT run on the first tick: tick() happens before
    the first render, so a slow command blocked the loop while the PREVIOUS screen
    was still on the panel — the device looked frozen. Now the first tick paints a
    'Working' frame (with the busy spinner) and the second tick actually runs it,
    so there is always visible feedback before anything blocks.
    """
    def __init__(self, title, cmd):
        self.title = title
        self.cmd = cmd
        self.lines = None            # None = still working
        self.top = 0
        self._frames = 0
        self._spin = 0

    def animating(self):
        return self.lines is None    # keep the spinner turning until it finishes

    def draw(self, c):
        if self.lines is None:
            _fit(c, 2, _TOP + _ROWH, 'Working...')
            spinner(c, c.w - 8, c.h - 8, self._spin)
            return
        rows = (c.h - _TOP) // _ROWH
        n = len(self.lines)
        if self.top > max(0, n - rows):
            self.top = max(0, n - rows)
        scrolls = n > rows
        right = c.w - (_SB_W + 1) if scrolls else c.w
        for i in range(rows):
            idx = self.top + i
            if idx >= n:
                break
            _fit(c, 2, _TOP + i * _ROWH, self.lines[idx])
        if scrolls:
            scrollbar(c, right + 1, _TOP, c.h - _TOP, self.top, rows, n)

    def tick(self, dt_ms=0):
        if self.lines is not None:
            return False
        self._frames += 1
        self._spin += 1
        if self._frames < 2:
            return True              # paint 'Working' BEFORE blocking
        self.lines = _run_capture(self.cmd) or ['(no output)']
        return True

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.top += 1
        elif e == ev.ROT_CCW:
            self.top = max(0, self.top - 1)
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


def _lock_editor():
    """Open the editor matching the configured lock kind. One 'Change code' row
    instead of a Set-PIN row and a Set-password row, only one of which ever
    applies."""
    if str(_reg('Apps.NovaD1_Lock_Kind', 'pin')).lower() == 'password':
        return PasswordScreen('set')
    return PinScreen('set')


def _mk_group(title, fn):
    return lambda: SettingsScreen(title, fn())


def _rows_display():
    return [
        ('push', 'Brightness', DisplayScreen),
        ('cycle', 'Dim After', 'Apps.NovaD1_DimSec', ['0', '5', '15', '30', '60'],
         '15', None),
        ('cycle', 'Screen Off', 'Apps.NovaD1_OffSec', ['0', '30', '60', '120', '300'],
         '60', None),
        ('cycle', 'Invert', 'Apps.NovaD1_Invert', ['off', 'on'], 'off', _apply_invert),
        ('cycle', 'Panel', 'Apps.NovaD1_Display', ['sh1106', 'ssd1306', 'ssd1309'],
         'sh1106', None),
    ]


def _rows_home():
    all_for_cfg = [(k, l) for k, l, _f in _all_apps() if not k.startswith('script_')]
    cur = _home_keys() or [k for k, _l in all_for_cfg]
    return [
        ('cycle', 'Layout', 'Apps.NovaD1_HomeStyle', ['folders', 'gallery', 'menu'],
         'folders', None),
        ('push', 'Manage Apps', lambda: ManageAppsScreen(all_for_cfg, cur)),
        ('cycle', 'Chime', 'Apps.NovaD1_Chime', ['on', 'off'], 'on', None),
        ('cycle', 'Notify', 'Apps.NovaD1_Notify', ['on', 'off'], 'on', None),
        ('cycle', 'Alert LED', 'Apps.NovaD1_Notify_LED', ['on', 'off'], 'on', None),
    ]


def _rows_radar():
    return [
        ('cycle', 'Observer', 'Apps.NovaD1_Watch', ['on', 'off'], 'on', None),
        ('cycle', 'Scan every', 'Apps.NovaD1_Watch_Period',
         ['4000', '8000', '20000', '60000'], '8000', None),
        ('cycle', 'Tell me', 'Apps.NovaD1_Watch_Notify', ['on', 'off'], 'on', None),
        ('cycle', 'New devices', 'Apps.NovaD1_Watch_New', ['off', 'on'], 'off', None),
        ('push', 'Presence', _presence_app),
    ]


def _rows_network():
    return [
        ('push', 'WiFi', WiFiScreen),
        ('cycle', 'LoRa MHz', 'Apps.NovaD1_LoRa_Freq', ['433', '868', '915'], '915',
         None),
        ('cycle', 'NTP Boot', 'Apps.NTP_On_Boot', ['false', 'true'], 'false', None),
        ('action', 'Sync Clock', 'ntp sync'),
        ('cycle', 'Web Panel', 'Apps.NovaD1_Web', ['off', 'on'], 'off', _apply_web),
        ('action', 'Web Info', 'novad1 web'),
    ]


class PrivacyScreen(Screen):
    """An inventory of what could identify this device, and whether it is closed.

    A list rather than a single "you are anonymous" indicator, because that claim
    would be false. Anonymity is a set of channels and closing four of five is not
    anonymity — showing which one is still open is the useful thing."""
    def __init__(self):
        self.title = 'Privacy'
        self.sel = 0

    def tick(self, dt_ms=0):
        return True

    def draw(self, c):
        import novastealth
        rows = novastealth.leaks()
        for i, (name, closed, note) in enumerate(rows):
            y = _TOP + i * _ROWH
            if y > c.h - 2 * _FH:
                break
            c.text(2, y, ('+' if closed else '!'), 1)
            _fit(c, 2 + _ADV, y, name, 1)
            st = 'ok' if closed else 'OPEN'
            c.text(c.w - c.text_width(st, 1, True) - 2, y, st, 1, 1, True)
        open_n = sum(1 for _n, closed, _t in rows if not closed)
        _fit(c, 2, c.h - _FH,
             'All closed. Sel=Ghost' if not open_n
             else '{} open. Sel=Ghost'.format(open_n))

    def on_event(self, e):
        if e in (ev.SELECT, ev.SELECT_HOLD):
            import novastealth
            novastealth.ghost()
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


def _rows_security():
    return [
        ('cycle', 'Lock type', 'Apps.NovaD1_Lock_Kind', ['pin', 'password'], 'pin',
         None),
        ('push', 'Change code', _lock_editor),
        ('action', 'Clear lock', 'novad1 pin clear'),
        ('cycle', 'Auto-Lock', 'Apps.NovaD1_LockSec', ['0', '5', '15', '30', '60'],
         '5', None),
        ('push', 'Privacy', _mk_group('Privacy', _rows_privacy)),
    ]


def _rows_privacy():
    """Radio identity, kept apart from the device lock. They are different
    questions: one is who can pick this up, the other is who can recognise it."""
    return [
        ('cycle', 'Incognito', 'Apps.NovaD1_Stealth', ['off', 'on'], 'off',
         _apply_stealth),
        ('cycle', 'Random ID', 'Apps.NovaD1_RandomMAC', ['on', 'off'], 'on', None),
        ('push', 'What leaks', PrivacyScreen),
    ]


def _rows_system():
    return [
        ('push', 'Set Time', TimeScreen),
        ('cycle', 'Dyn Clock', 'Settings.Dynamic_Clock', ['false', 'true'], 'false',
         None),
        ('cycle', 'Verbose', 'Settings.Verbose_Boot', ['false', 'true'], 'false', None),
        ('cycle', 'SD Card', 'Features.SD_Support', ['false', 'true'], 'false', None),
        ('push', 'Updates', UpdatesScreen),
        ('push', 'Reboot', RebootScreen),
    ]


def _settings_index():
    """The top level: six groups, exactly one screen, nothing to scroll past."""
    return [
        ('push', 'Display', _mk_group('Display', _rows_display)),
        ('push', 'Home', _mk_group('Home', _rows_home)),
        ('push', 'Network', _mk_group('Network', _rows_network)),
        ('push', 'Radar', _mk_group('Radar', _rows_radar)),
        ('push', 'Security', _mk_group('Security', _rows_security)),
        ('push', 'System', _mk_group('System', _rows_system)),
    ]


class SettingsScreen(Screen):
    """Grouped settings. Rows:
       ('head', label) — a section title (skipped by navigation)
       ('push', label, factory) — opens a sub-screen
       ('cycle', label, regkey, [values], default, apply) — flips a saved value
       ('action', label, shell-cmd) — runs an OS command, shows output.

    Settings used to be ONE list of 31 rows: five screens of scrolling to reach
    anything, which is what made it feel cluttered. It's now a six-row index where
    every group fits a single screen, so nothing below the top level scrolls."""
    def __init__(self, title='Settings', rows=None):
        self.title = title
        self.top = 0
        self.rows = rows if rows is not None else _settings_index()
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
        # Keep the section header visible. Headers can't be selected, so scrolling
        # into a section pushed its 'DISPLAY'/'HOME' title off the top and you lost
        # track of which group you were in. If the row just above the window is a
        # header, pull it into view.
        if self.top > 0 and self.rows[self.top - 1][0] == 'head' \
                and (self.sel - (self.top - 1)) < rows:
            self.top -= 1
        n = len(self.rows)
        scrolls = n > rows
        # Reserve a lane for the scrollbar. The old up/down triangles sat ON the
        # rows, so a highlighted row swallowed them; a lane can't collide.
        right = c.w - (_SB_W + 1) if scrolls else c.w
        for i in range(rows):
            idx = self.top + i
            if idx >= n:
                break
            r = self.rows[idx]
            y = _TOP + i * _ROWH
            if r[0] == 'head':
                lbl = r[1][:14]
                c.text(2, y, lbl, 1)
                lw = c.text_width(lbl)
                c.hline(2 + lw + 2, y + _FH // 2, max(0, right - (lw + 8)), 1)
                continue
            inv = (idx == self.sel)
            if inv:
                rounded_rect(c, 0, y - 1, right, _ROWH, 1)
            tc = 0 if inv else 1
            if r[0] in ('push', 'action'):
                c.text(7, y, r[1], tc)
                c.text(right - _ADV - 2, y, '>', tc)
            else:
                v = self._val(r)
                vw = c.text_width(v)
                lbl = r[1]
                avail = right - vw - 12
                while lbl and c.text_width(lbl) > avail:
                    lbl = lbl[:-1]
                c.text(7, y, lbl, tc)
                c.text(right - vw - 2, y, v, tc)
        if scrolls:
            scrollbar(c, right + 1, _TOP, c.h - _TOP, self.top, rows, n)

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
    scripts = [a for a in apps if a[0].startswith('script_') or a[0].startswith('pyapp_')]
    apps = [a for a in apps if not (a[0].startswith('script_') or a[0].startswith('pyapp_'))]
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


def _favorite_keys():
    """App keys the user pinned to the home's favorites bar (Apps.NovaD1_Favorites,
    comma-separated), in order. Empty by default."""
    raw = _reg('Apps.NovaD1_Favorites', '')
    return [k.strip() for k in raw.split(',') if k.strip()]


def _build_folder_home(triples):
    """Group apps by category into folders — the top level shows any FAVORITES first
    (direct launchers for the most-used apps), then a folder per category (Wireless /
    Sensors / Tools / System); opening one shows just that category's apps. Friendlier
    than one long ring of 18+ icons. Uncategorised or empty -> the flat gallery."""
    by_cat = {}
    tmap = {}
    for key, label, fac in triples:
        by_cat.setdefault(_app_category(key), []).append((key, label, fac))
        tmap[key] = (key, label, fac)
    items = []
    # Favorites bar: pinned apps launch directly from the top of the home, and still
    # appear inside their category folder.
    for k in _favorite_keys():
        if k in tmap:
            items.append(tmap[k])
    for cat in _CATEGORIES:
        apps = by_cat.get(cat)
        if apps:
            items.append((_CAT_ICON.get(cat, 'app'),
                          '{} ({})'.format(cat, len(apps)), _mk_folder(cat, apps)))
    if len(items) < 2:
        return IconGallery('Nova D1', triples)
    return IconGallery('Nova D1', items)
