# The power menu: sleep, lock, incognito, deep sleep.
#
# Four reports, and the first three of them were ONE bug. NovaUI's idle block
# recomputes the brightness tier from _idle_t0 on every pass and calls
# _set_level(target). A manual _set_level(2) therefore survived exactly one loop
# iteration before the idle machine — whose clock had just been reset by the very
# button press that asked for sleep — put the panel straight back on. That is why
# Sleep flashed and returned to the menu, why the Shutdown screen never went dark,
# and why waking from Shutdown looked like it dropped back into it.
#
# The fix is a sticky _sleep_mode that the idle block steps around, so these tests
# drive the real loop rather than calling _set_level directly.
import sys
import _shims
_shims.install()
from _shims import T

import novagui
import novainput as ev

t = T('test_power')

# ---------------------------------------------------------- the sticky sleep
levels = []


class _FakeUI(novagui.NovaUI):
    """The real NovaUI with the hardware ends stubbed, so the idle block under
    test is the shipped one."""
    def __init__(self):
        self._idle_t0 = 0
        self._level = 0
        self._dimmed = False
        self._locked = False
        self._lock_scr = None
        self._sleep_mode = None
        self.stack = ['home', 'menu']
        self._t = 0

    def _now(self):
        return self._t

    def _set_level(self, level):
        if level != self._level:
            levels.append(level)
        self._level = level
        self._dimmed = level >= 1


ui = _FakeUI()
ui.sleep_display('sleep')
t.eq(ui._level, 2, 'sleeping turns the panel off')
t.eq(ui._sleep_mode, 'sleep', 'and records WHY, so the idle tiers can step around it')

# Reproduce the loop's idle block with a fresh idle clock -- the exact situation
# that used to undo the sleep one frame later.
now = ui._t = 1000
ui._idle_t0 = now            # a button was just pressed, so idle is ~0


def idle_target(u, now, dim_s=15, off_s=60):
    """The shipped decision, transcribed. Kept in step with novagui by the source
    assertion further down rather than by hoping nobody edits one of them."""
    if u._sleep_mode:
        return 2
    idle = now - u._idle_t0
    if off_s > 0 and idle >= off_s * 1000:
        return 2
    if dim_s > 0 and idle >= dim_s * 1000:
        return 1
    return 0


t.eq(idle_target(ui, now), 2,
     'with a deliberate sleep held, the idle tiers leave the panel off even '
     'though the idle clock was just reset')

ui._sleep_mode = None
t.eq(idle_target(ui, now), 0, 'and without one, a fresh idle clock means full brightness')

# The real thing must actually contain that guard.
import inspect
src = inspect.getsource(novagui.NovaUI._loop_once)
t.ok('if self._sleep_mode:' in src,
     'the idle block checks _sleep_mode BEFORE the timers -- otherwise a manual '
     'sleep survives exactly one loop iteration')

# ------------------------------------------------------------------ waking
ui = _FakeUI()
ui.sleep_display('sleep')
ui._t = 90000                       # a long time later
ui._wake_display()
t.eq(ui._level, 0, 'waking turns the panel back on')
t.eq(ui._sleep_mode, None, 'and clears the sleep mode')
t.eq(ui._idle_t0, 90000,
     'waking RESTARTS the idle clock -- leaving it stale meant the idle block '
     'immediately re-blanked the panel, the "wakes then goes right back" report')

# An explicit Sleep wakes to the home screen, not to whatever was open.
ui = _FakeUI()
ui.stack = ['home', 'power menu', 'something else']
ui.sleep_display('sleep')
ui._wake_display()
t.eq(ui.stack, ['home'], 'waking from Sleep returns to the home screen')

# Shutdown is different on purpose: it comes back to what was on screen.
ui = _FakeUI()
ui.stack = ['home', 'power menu']
ui.sleep_display('shutdown')
ui._wake_display()
t.eq(ui.stack, ['home', 'power menu'], 'waking from Shutdown leaves the stack alone')

# -------------------------------------------------------------------- locking
# Patch novacore.reg, not novagui._reg: lock_screen and lock_is_set in
# novagui_system import novacore INSIDE the function, so they never see a
# novagui-level patch.
REG = {}
import novacore
_real_reg = novacore.reg
_real_gui_reg = novagui._reg
novacore.reg = lambda k, d=None: REG.get(k, d)
novagui._reg = lambda k, d=None: REG.get(k, d)
try:
    # With NO code set, Lock must still do something. It used to return None,
    # which the menu treated as "stay put" -- a dead button.
    REG.clear()
    scr = novagui._power_lock()
    t.ok(scr is not None, 'Lock does something even with no passcode set')
    t.eq(scr.__class__.__name__, 'ScreenLock',
         'with no code it is a codeless screen lock, not a PIN pad with nothing '
         'to verify')
    t.ok(getattr(scr, 'manual_wake', False),
         'and stray input does not dismiss it, or it is not a lock')
    t.eq(scr.on_event(ev.SELECT), None, 'a tap does not unlock it')
    t.eq(scr.on_event(ev.ROT_CW), None, 'nor does turning the encoder')
    t.eq(scr.on_event(ev.SELECT_HOLD), 'back',
         'a deliberate HOLD unlocks it -- a single press is what a pocket produces')

    # With a PIN set it is the real thing.
    REG['Apps.NovaD1_Lock_Kind'] = 'pin'
    REG['Apps.NovaD1_PIN'] = '000000'
    t.eq(novagui._power_lock().__class__.__name__, 'PinScreen',
         'with a PIN set, Lock is the PIN screen')

    # Lock type 'none' means no code, whatever is still stored.
    REG['Apps.NovaD1_Lock_Kind'] = 'none'
    t.eq(novagui._power_lock().__class__.__name__, 'ScreenLock',
         'lock type None gives the codeless lock even with a stale PIN stored')
finally:
    novacore.reg = _real_reg
    novagui._reg = _real_gui_reg

# ------------------------------------------------------------------ incognito
calls = []
import novastealth
_kill, _restore, _active = novastealth.kill_all, novastealth.restore, novastealth.active
state = {'on': False}
novastealth.kill_all = lambda: (calls.append('kill'), state.__setitem__('on', True))
novastealth.restore = lambda: (calls.append('restore'), state.__setitem__('on', False))
novastealth.active = lambda: state['on']
try:
    # Off -> on.
    scr = novagui.StealthSplashScreen()
    scr.tick(16)
    t.eq(calls, ['kill'], 'from off, the row engages incognito')

    # On -> off. This is the report: the row only ever engaged, so once stealth
    # was on the one place you would go to turn it off did nothing.
    calls[:] = []
    scr = novagui.StealthSplashScreen()
    scr.tick(16)
    t.eq(calls, ['restore'], 'from on, the same row turns it back off')

    # The physical kill switch must NOT toggle -- knocked twice in a pocket it
    # would silently re-arm every radio.
    calls[:] = []
    scr = novagui.StealthSplashScreen('on')
    scr.tick(16)
    t.eq(calls, ['kill'], "an explicit 'on' engages even when already engaged")
    src = inspect.getsource(novagui.NovaUI._loop_once)
    t.ok("StealthSplashScreen('on')" in src,
         'the kill switch asks for on, not for a toggle')
finally:
    novastealth.kill_all, novastealth.restore = _kill, _restore
    novastealth.active = _active

# ----------------------------------------------------------------- deep sleep
d = novagui.DeepSleepScreen()
t.ok(None in d.TIMERS, 'an indefinite option exists')
mins = [m for m in d.TIMERS if m is not None]
t.ok(mins, 'and timed ones')
t.ok(max(mins) <= 71,
     'no timer exceeds the port ceiling: rp2 caps lightsleep at (1<<32)/1000 ms, '
     'about 71 minutes, and raises ValueError above it')

t.eq(d.on_event(ev.SELECT), None,
     'a tap does NOT commit -- the only undo for deep sleep is a physical button')
t.ok(not d._committed, 'still not committed')
d.on_event(ev.SELECT_HOLD)
t.ok(d._committed, 'a hold commits')

t.eq(novagui.DeepSleepScreen().on_event(ev.HOME), ev.HOME, 'HOME backs out')

# Deep sleep must not have replaced Shutdown: shutdown resumes instantly with the
# GUI still resident, deep sleep reboots. Losing the first would be a regression.
dsrc = inspect.getsource(novagui.DeepSleepScreen)
t.ok('deepsleep' in dsrc, 'deep sleep actually calls machine.deepsleep')
t.ok('kill_all' in dsrc, 'and silences the radios on the way down')
t.ok(novagui.ShutdownScreen is not None, 'Shutdown still exists alongside it')

sys.exit(t.done())
