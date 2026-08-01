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
    ('stealth', novagui.StealthSplashScreen),
    ('shutdown', novagui.ShutdownScreen),
    ('splash', novagui.SplashScreen),
    ('text_long', lambda: novagui.TextScreen('T', [
        'a line long enough to need wrapping on a tiny panel for sure', 'b'])),
    ('wardrive', novagui_radios.WardriveScreen),
    ('gps', novagui_radios.GPSScreen),
    ('messages', novagui_radios.MessagesScreen),
    ('ircapture', novagui_radios.IRCaptureScreen),
    ('wifi', novagui_system.WiFiScreen),
    ('time', novagui_system.TimeScreen),
    ('notifications', novagui_system.NotificationsScreen),
    ('led', novagui_sensors.LedScreen),
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

sys.exit(t.done())
