# Every screen must stay INSIDE the 128x64 panel. Text that ran off the right edge
# was a real, reported bug (status lines, error strings and footers were drawn at the
# fixed 8px cell and silently clipped). This renders each screen with an instrumented
# canvas that fails on any glyph past the edge, so a regression can't ship.
import sys
import _shims
_shims.install()
from _shims import T

import novacanvas
import novagui
import novagui_radios
import novagui_system
import novagui_sensors
import novagui_watch

t = T('test_screenfit')

_orig_text = novacanvas.Canvas.text
_bad = []
_cur = {'n': '?'}


def _checked_text(self, x, y, s, c=1, scale=1, narrow=False):
    if s:
        w = self.text_width(s, scale, narrow)
        if x + w > self.w + 1:
            _bad.append('{}: {!r} runs {}px past the edge'.format(
                _cur['n'], s, (x + w) - self.w))
        if y + 8 * scale > self.h + 1:
            _bad.append('{}: {!r} runs off the bottom'.format(_cur['n'], s))
    return _orig_text(self, x, y, s, c, scale, narrow)


novacanvas.Canvas.text = _checked_text

STATE = {'time': '12:34', 'wifi': True, 'notify': 3, 'title': 'Nova D1',
         'power': {'have': True, 'usb': True, 'pct': 88, 'low': False}}

SCREENS = (
    ('home_folders', lambda: novagui.build_home({}, 'folders')),
    ('home_gallery', lambda: novagui.build_home({}, 'gallery')),
    ('home_menu', lambda: novagui.build_home({}, 'menu')),
    ('power', novagui._power_menu),
    ('troubleshoot', novagui._troubleshoot_menu),
    ('commands', novagui._commands_menu),
    ('settings', novagui._settings_menu),
    # Each settings GROUP too — they're the screens the top level pushes into, and
    # they carry the long value strings (panel names, timeouts) most likely to run
    # off the right edge.
    ('settings_display', novagui._mk_group('Display', novagui._rows_display)),
    ('settings_home', novagui._mk_group('Home', novagui._rows_home)),
    ('settings_network', novagui._mk_group('Network', novagui._rows_network)),
    ('settings_security', novagui._mk_group('Security', novagui._rows_security)),
    ('settings_privacy', novagui._mk_group('Privacy', novagui._rows_privacy)),
    ('privacy_leaks', novagui.PrivacyScreen),
    ('settings_system', novagui._mk_group('System', novagui._rows_system)),
    ('stealth', novagui.StealthSplashScreen),
    ('shutdown', novagui.ShutdownScreen),
    ('splash', novagui.SplashScreen),
    ('text_long', lambda: novagui.TextScreen('T', [
        'a line long enough to need wrapping on a tiny panel for sure', 'b'])),
    ('wardrive', novagui_radios.WardriveScreen),
    ('radar', novagui_watch.RadarScreen),
    ('radar_settings', lambda: novagui.SettingsScreen('Radar', novagui._rows_radar())),
    ('device', lambda: novagui_watch.DeviceScreen('44:19:b6:00:11:22')),
    ('locate', lambda: novagui_watch.LocateScreen('44:19:b6:00:11:22')),
    ('presence', novagui_watch.PresenceScreen),
    ('gps', novagui_radios.GPSScreen),
    ('messages', novagui_radios.MessagesScreen),
    ('ircapture', novagui_radios.IRCaptureScreen),
    ('wifi', novagui_system.WiFiScreen),
    ('time', novagui_system.TimeScreen),
    ('notifications', novagui_system.NotificationsScreen),
    ('battery', novagui_sensors.BatteryScreen),
    ('environment', novagui_sensors.EnvironmentScreen),
)

for name, factory in SCREENS:
    _cur['n'] = name
    try:
        scr = factory()
        cv = novacanvas.Canvas(128, 64)
        scr.tick(40)
        if not getattr(scr, 'fullscreen', False):
            st = dict(STATE)
            st['title'] = getattr(scr, 'title', name)
            novagui.draw_status_bar(cv, st)
        scr.draw(cv)
        t.ok(True, '{} renders'.format(name))
    except Exception as e:
        t.ok(False, '{} raised: {}'.format(name, e))

# The status bar in every power state (the icons + title + clock must coexist).
for nm, pwr in (('usb', {'have': False, 'usb': True}),
                ('battery', {'have': True, 'usb': False, 'pct': 55, 'low': False}),
                ('no-sense', {'have': False, 'usb': False}),
                ('charging', {'have': True, 'usb': True, 'pct': 90, 'low': False})):
    _cur['n'] = 'bar_' + nm
    cv = novacanvas.Canvas(128, 64)
    st = dict(STATE)
    st['power'] = pwr
    st['title'] = 'Nova D1 Longish'
    novagui.draw_status_bar(cv, st)
    t.ok(True, 'status bar ({}) renders'.format(nm))

t.ok(not _bad, 'nothing overflows the panel:\n    ' + '\n    '.join(_bad[:8]))

# A battery indicator must show even with no sense pin (running on VSYS), so the
# bar never looks like there's no power source at all.
_cur['n'] = 'bar_probe'
drawn = []
_orig_batt = novagui._battery
novagui._battery = lambda c, x, y, pct, low=False: drawn.append(('batt', pct))
try:
    cv = novacanvas.Canvas(128, 64)
    st = dict(STATE)
    st['power'] = {'have': False, 'usb': False}
    novagui.draw_status_bar(cv, st)
    t.ok(drawn and drawn[0][1] == 0, 'no USB + no sense pin -> EMPTY battery icon')
finally:
    novagui._battery = _orig_batt

# Settings must not scroll below the top level. The whole point of splitting the
# old 31-row list into groups was that you stop hunting through screens of rows —
# a group that overflows has quietly undone that.
_ROWS_VISIBLE = (64 - novagui._TOP) // novagui._ROWH
for name, fn in (('index', novagui._settings_index),
                 ('Display', novagui._rows_display), ('Home', novagui._rows_home),
                 ('Network', novagui._rows_network),
                 ('Security', novagui._rows_security),
                 ('Privacy', novagui._rows_privacy),
                 ('System', novagui._rows_system)):
    n = len(fn())
    t.ok(n <= _ROWS_VISIBLE,
         'settings {} fits one screen ({} rows, {} fit)'.format(name, n, _ROWS_VISIBLE))

# Every screen title must fit the status bar. 'Troubleshoot' rendering as
# 'Trouble' was a reported bug, and it isn't a rendering bug — the bar is only
# ~55px wide once the clock and four icons have taken their share, so titles have
# to be short BY DESIGN. This is the assertion that keeps them that way.
_budget = novagui.title_budget(novacanvas.Canvas(128, 64))
_probe = novacanvas.Canvas(128, 64)
_seen = set()
for name, factory in SCREENS:
    try:
        scr = factory()
    except Exception:
        continue
    ttl = getattr(scr, 'title', None)
    if not ttl or ttl in _seen:
        continue
    _seen.add(ttl)
    t.ok(_probe.text_width(ttl, 1, True) <= _budget,
         'title {!r} fits the status bar ({}px)'.format(ttl, _budget))

for _k, _lbl, _f in novagui._all_apps():
    if _k.startswith(('script_', 'pyapp_')):
        continue
    t.ok(_probe.text_width(_lbl, 1, True) <= _budget,
         'app name {!r} fits the status bar'.format(_lbl))

sys.exit(t.done())
