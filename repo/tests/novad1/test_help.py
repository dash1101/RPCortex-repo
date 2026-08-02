# Controls are documented, not printed on every frame.
#
# Screens with a non-obvious gesture each spent their bottom ROW on a hint —
# 'Sel=rec', 'turn=adjust  OK=save'. On a panel six rows tall that is a sixth of
# the display permanently given to text you read once, and it is why lists showed
# five entries instead of six.
#
# The hints now live in a `help` tuple, reachable from the Controls entry in the
# hold-HOME menu (already the universal gesture, so no new one to learn), with a
# '?' in the status bar so a documented screen is still discoverable.
import sys
import inspect
import _shims
_shims.install()
from _shims import T

import novacanvas
import novainput as ev
import novaui
import novagui
import novagui_system
import novagui_sensors
import novagui_radios
import novagui_shell
import novagui_res

t = T('test_help')

# ------------------------------------------------------------- the convention
t.eq(novaui.Screen.help, (), 'a screen documents no controls by default')
t.ok(hasattr(novaui, 'HelpScreen'), 'the leaf provides the Controls screen')

h = novaui.HelpScreen('Shell', ('hold SELECT = keyboard',))
t.ok('hold SELECT = keyboard' in h.lines, 'it shows the screen it was given')
for u in novaui.HelpScreen.UNIVERSAL:
    t.ok(u in h.lines, 'and always appends the universal control {!r}'.format(u))

c = novacanvas.Canvas(128, 64)
h.draw(c)
t.ok(True, 'it draws')
t.eq(h.on_event(ev.BACK), 'back', 'BACK closes it')
t.eq(h.on_event(ev.SELECT), 'back', 'so does SELECT')
h.top = 0
h.on_event(ev.ROT_CCW)
t.eq(h.top, 0, 'scrolling up at the top does not go negative')

# A long help list must scroll rather than run off the panel.
long_h = novaui.HelpScreen('X', tuple('line {}'.format(i) for i in range(20)))
long_h.draw(c)
t.ok(long_h.top <= max(0, len(long_h.lines) - long_h._visible(c)),
     'a long list is clamped, not drawn past the end')

# ------------------------------------------------------ screens carry their help
DOCUMENTED = (
    (novagui_system.WiFiScreen, 'WiFi'),
    (novagui_system.TimeScreen, 'Set Time'),
    (novagui_system.TZScreen, 'Timezone'),
    (novagui_system.NotificationsScreen, 'Alerts'),
    (novagui_system.ScreenLock, 'the lock'),
    (novagui_sensors.ClockScreen, 'Clock'),
    (novagui_radios.IRCaptureScreen, 'IR capture'),
    (novagui_shell.ShellScreen, 'Shell'),
    (novagui_res.ResourcesScreen, 'Resources'),
)
for cls, label in DOCUMENTED:
    hp = getattr(cls, 'help', ())
    t.ok(hp, '{} documents its controls'.format(label))
    t.ok(all(isinstance(x, str) and x for x in hp),
         '{}: every help line is a non-empty string'.format(label))
    # A help line has to fit the panel or the manual is itself clipped.
    for ln in hp:
        t.ok(c.text_width(ln) <= c.w - 4,
             '{}: help line {!r} fits the panel'.format(label, ln))

# ------------------------------------------------- the hints are OFF the screen
# The point of the change: the static hint no longer costs a row on every frame.
for mod, needle in ((novagui_system, "'OK=scan   hold=add'"),
                    (novagui_system, "'Sel=field  Sel-hold=set'"),
                    (novagui_system, "'Sel=clear'"),
                    (novagui_sensors, "'turn: stopwatch'"),
                    (novagui_radios, "'Sel=rec'")):
    t.ok(needle not in inspect.getsource(mod),
         'the static hint {} is gone from the draw path'.format(needle))

# A dynamic STATUS message is different and must survive — it is feedback about
# what just happened, not a manual.
rsrc = inspect.getsource(novagui_radios)
t.ok('if self.msg:' in rsrc,
     'status messages are still drawn when there is one to show')

# ------------------------------------------------------------- discoverability
t.ok("state.get('help')" in inspect.getsource(novagui.draw_status_bar),
     "the status bar marks a documented screen, so removing the hints does not "
     'make them undiscoverable')
t.ok("st['help']" in inspect.getsource(novagui.NovaUI.render),
     'and the runner supplies that flag from the live screen')

# ------------------------------------------------------------- reachable at all
t.ok(any(r[0] == 'Controls' for r in novagui._power_menu().items)
     if hasattr(novagui._power_menu(), 'items')
     else 'Controls' in str(novagui._power_menu().__dict__),
     'Controls is in the hold-HOME menu')


class _Doc:
    title = 'Documented'
    help = ('turn = do a thing',)
    def draw(self, c): pass
    def on_event(self, e): return None


import display
ui = novagui.NovaUI(display.MockDisplay(128, 64), novacanvas.Canvas(128, 64),
                    ev.ScriptedSource(), {}, _Doc())
novagui._active_ui = ui
ui.handle(ev.HOME_HOLD)                      # opens the power menu over it
scr = novagui._controls_for_current()
t.eq(scr.__class__.__name__, 'HelpScreen', 'Controls opens the help screen')
t.ok('turn = do a thing' in scr.lines,
     'showing the controls for the screen you came FROM, not the power menu')
t.eq(scr.name, 'Documented', 'and names that screen')

# ------------------------------------------------ the alert shares the net slot
# 128px against five icons leaves about 52px of title. A permanent sixth icon for
# an alert would have come straight out of that, so the bell alternates with the
# network glyph instead of claiming its own space.
import novacanvas as _nc


def _bar(**st):
    base = {'time': '19:42', 'wifi': True, 'title': 'Nova D1',
            'power': {'have': True, 'pct': 70, 'usb': False, 'low': False}}
    base.update(st)
    cv = _nc.Canvas(128, 64)
    novagui.draw_status_bar(cv, base)
    return bytes(cv.buf)


plain = _bar(notify=False)
ph0 = _bar(notify=True, alert_phase=0)
ph1 = _bar(notify=True, alert_phase=1)
t.eq(ph0, plain, 'on one half of the cycle the bar looks exactly as it always did')
t.ok(ph1 != plain, 'and on the other the alert has replaced the network glyph')

# The title must not shrink when an alert arrives -- that was the whole point.
wide = _bar(notify=True, alert_phase=1, title='Resources')
narrow = _bar(notify=False, title='Resources')
t.ok(wide != narrow, 'the two phases differ')
src = inspect.getsource(novagui.draw_status_bar)
t.ok(src.count('x -= 9') <= 1,
     'the alert claims no extra horizontal slot -- only the SD-save icon does')

# With the radio off there is nothing to alternate with, so the bell just sits.
off0 = _bar(notify=True, wifi=False, alert_phase=0)
off1 = _bar(notify=True, wifi=False, alert_phase=1)
t.eq(off0, off1,
     'with the radio off the bell is steady rather than blinking against a blank')

# The phase has to be part of the repaint signature or the swap would only happen
# when something else made the frame dirty.
t.ok("phase" in inspect.getsource(novagui.NovaUI._loop_once),
     'the alert phase drives a repaint, so the alternation actually animates')
t.ok(novagui._ALERT_CYCLE_MS >= 500,
     'the cycle is slow enough to read as a swap, not a flicker')

sys.exit(t.done())
