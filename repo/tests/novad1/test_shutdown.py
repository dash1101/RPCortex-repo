# ShutdownScreen: powering down must not need RAM to come back.
#
# It used to reboot on any button press, which meant reloading the whole GUI —
# and on a device that had been running a while there was no longer enough
# contiguous RAM to do it, so "turning it back on" failed. The GUI stays resident
# the entire time; waking only has to turn the panel back on. A deliberate
# three-second HOME hold is required so a knock in a pocket cannot light it up.
import sys
import _shims
_shims.install()
from _shims import T
import novagui, novacanvas
from novaui import ev

t = T('shutdown')

class _Src:
    def __init__(s): s.held = 0
    def poll(s): return None
    def held_ms(s, e): return s.held if e == ev.HOME else 0

class _UI:
    def __init__(s): s.slept = 0; s.woke = 0; s.mode = None; s.source = _Src()
    def sleep_display(s, mode='sleep'): s.slept += 1; s.mode = mode
    def _wake_display(s): s.woke += 1; s.mode = None

ui = _UI()
novagui._active_ui = ui
scr = novagui.ShutdownScreen()
c = novacanvas.Canvas(128, 64)

scr.tick(40)                                  # first tick kills radios
t.eq(ui.slept, 0, 'the screen does not go dark immediately')
scr.draw(c)
t.ok(True, 'it renders while counting down')

for _ in range(int(novagui.ShutdownScreen.SHOW_MS / 100) + 2):
    scr.tick(100)
t.eq(ui.slept, 1, 'the panel turns itself off after the countdown')
# The mode passed here is what KEEPS it dark. It used to be a bare _set_level(2),
# which the runner's idle-tier block recomputed and undid on the very next pass --
# so this screen said "powered down" with the panel still lit, and the later wake
# appeared to drop straight back into it.
t.eq(ui.mode, 'shutdown',
     'shutdown sleeps under its own mode, so waking returns to what was on screen '
     'rather than resetting to home')

# ordinary input must NOT wake it
for e in (ev.SELECT, ev.BACK, ev.ROT_CW, ev.HOME):
    t.ok(scr.on_event(e) is None, '{} does not wake it'.format(e))
t.eq(ui.woke, 0, 'and nothing woke the panel')

ui.source.held = 500
scr.tick(100)
t.eq(ui.woke, 0, 'a brief HOME hold is not enough')

ui.source.held = novagui.ShutdownScreen.HOLD_WAKE_MS + 10
r = scr.tick(100)
t.eq(ui.woke, 1, 'a three-second HOME hold wakes it')
t.eq(r, 'back', 'and returns to what was on screen')

# The old behaviour rebooted, which meant reloading the GUI — and on a device
# that had been up a while there was no longer the RAM to do it.
import inspect
src = inspect.getsource(novagui.ShutdownScreen)
t.ok('RebootScreen' not in src,
     'waking does not reboot: the GUI is still resident, only the panel is off')
t.ok(novagui.ShutdownScreen.manual_wake is True,
     'the screen opts out of wake-on-any-input')

t.eq(ui.mode, None, 'and waking clears the sleep mode, so the idle tiers resume')

sys.exit(t.done())
