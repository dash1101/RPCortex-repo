# Background jobs, the universal HOME escape, and the new system screens.
#
# The device runs ONE cooperative event loop shared by the GUI, the serial shell
# and every background service. A screen doing slow work inside tick() stops all
# of it: nothing repaints (so the "still working" spinner freezes, saying the
# opposite of what it means) and no button can be acted on. That is what made
# checking for updates lock the device for ten seconds or more.
#
# novajob moves that work onto the loop as a task. These tests check the job
# lifecycle, that cancellation actually reaches a parked coroutine, and that HOME
# gets you out of any screen that does not deliberately trap it.
import sys
import asyncio
import _shims
_shims.install()
from _shims import T

import novajob

t = T('test_novajob')


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------- the lifecycle
async def _ok(job):
    job.status = 'step one'
    await asyncio.sleep(0)
    job.status = 'step two'
    return 42


async def _lifecycle():
    j = novajob.start(_ok, status='starting')
    t.eq(j.state, novajob.RUNNING, 'a job starts running')
    t.ok(j.running(), 'and reports itself as running')
    t.eq(j.status, 'starting', 'with the status it was given')
    t.eq(j.result, None, 'and no result yet')
    for _ in range(20):
        await asyncio.sleep(0)
        if not j.running():
            break
    t.eq(j.state, novajob.DONE, 'it finishes')
    t.eq(j.result, 42, 'carrying the return value')
    t.eq(j.status, 'step two', 'and the last status it reported')
    t.eq(j.error, '', 'with no error')
    t.ok(not j.failed(), 'and it did not fail')


run(_lifecycle())


# ------------------------------------------------------------------- failures
async def _boom(job):
    raise OSError('connection reset')


async def _failure():
    j = novajob.start(_boom)
    for _ in range(20):
        await asyncio.sleep(0)
        if not j.running():
            break
    t.eq(j.state, novajob.ERROR, 'a raising job ends in error')
    t.ok(j.failed(), 'and reports failure')
    t.ok('connection reset' in j.error, 'carrying the reason, for the screen to show')


run(_failure())


# An exception with no message must still produce something to display -- an
# empty error box tells the user nothing.
async def _bare(job):
    raise MemoryError


async def _bare_msg():
    j = novajob.start(_bare)
    for _ in range(20):
        await asyncio.sleep(0)
        if not j.running():
            break
    t.ok(j.error, 'an exception with no message still yields text to show')


run(_bare_msg())


# ---------------------------------------------------------------- cancellation
async def _forever(job):
    for _ in range(10000):
        if job.cancelled():
            return 'noticed'
        await asyncio.sleep(0)
    return 'ran out'


async def _cancel_cooperative():
    j = novajob.start(_forever)
    for _ in range(3):
        await asyncio.sleep(0)
    j.cancel()
    for _ in range(20):
        await asyncio.sleep(0)
        if not j.running():
            break
    t.ok(not j.running(), 'a cancelled job stops')
    t.eq(j.error, 'Cancelled',
         'and says it was cancelled, not that it crashed -- the user asked for it')


run(_cancel_cooperative())


# A coroutine parked on a long await never gets to check the flag, so cancel()
# has to reach it through the task as well.
async def _parked(job):
    await asyncio.sleep(30)
    return 'should not get here'


async def _cancel_parked():
    j = novajob.start(_parked)
    await asyncio.sleep(0)
    j.cancel()
    for _ in range(20):
        await asyncio.sleep(0)
        if not j.running():
            break
    t.ok(not j.running(),
         'cancelling reaches a coroutine parked on an await, not just one that '
         'is polling the flag')
    t.eq(j.result, None, 'and it never produced a result')


run(_cancel_parked())

# Cancelling twice, and cancelling something already finished, must be harmless.
j = novajob.Job()
j.state = novajob.DONE
j.cancel()
j.cancel()
t.ok(True, 'cancel is safe to call twice and on a finished job')

# ------------------------------------------------------------- no running loop
# Off the loop there is nothing to schedule onto. The job must come back already
# failed rather than sitting in RUNNING forever, which would leave a screen
# spinning on work that was never started.
j = novajob.start(_ok)
t.eq(j.state, novajob.ERROR, 'with no running loop the job fails immediately')
t.ok(j.error, 'with a reason')

# The spinner frames must actually differ, or it is not a spinner.
frames = [novajob.spin(i) for i in range(len(novajob.SPIN))]
t.eq(len(set(frames)), len(novajob.SPIN), 'every spinner frame is distinct')
t.eq(novajob.spin(0), novajob.spin(len(novajob.SPIN)), 'and it wraps')

# ------------------------------------------------------- the universal HOME out
import novagui
import novainput as ev
import novacanvas
import display


class _Deaf:
    """A screen that handles nothing. Before the runner-level escape this was a
    room with no door: HOME did nothing and the only way out was a reboot."""
    title = 'deaf'
    def draw(self, c): pass
    def on_event(self, e): return None


class _Modal(_Deaf):
    """A lock. HOME must NOT get out of this, or the lock is decorative."""
    modal = True


def _ui(top):
    return novagui.NovaUI(display.MockDisplay(128, 64), novacanvas.Canvas(128, 64),
                          ev.ScriptedSource(), {}, top)


ui = _ui('home')
ui.stack = ['home', _Deaf()]
ui.handle(ev.HOME)
t.eq(ui.stack, ['home'],
     'HOME escapes a screen that ignores it -- the guarantee belongs to the '
     'runner, not to each screen remembering to implement it')

ui = _ui('home')
ui.stack = ['home', _Deaf(), _Deaf()]
ui.handle(ev.HOME)
t.eq(len(ui.stack), 1, 'and it goes all the way home, not one level up')

ui = _ui('home')
m = _Modal()
ui.stack = ['home', m]
ui.handle(ev.HOME)
t.eq(len(ui.stack), 2, 'a modal screen is NOT escaped by HOME')
t.ok(ui.stack[-1] is m, 'it is still on top')

# Non-HOME events that a screen ignores must not move anything.
ui = _ui('home')
ui.stack = ['home', _Deaf()]
for e in (ev.BACK, ev.SELECT, ev.ROT_CW):
    ui.handle(e)
t.eq(len(ui.stack), 2, 'only HOME triggers the escape, not every ignored event')

# The lock screens must actually carry the flag.
import novagui_system
t.ok(getattr(novagui_system.ScreenLock, 'modal', False),
     'the codeless screen lock is modal')
t.ok(novagui_system.PinScreen('verify').modal, 'a verifying PIN screen is modal')
t.ok(not novagui_system.PinScreen('set').modal,
     "but SETTING a PIN is not -- HOME should abandon an edit")
t.ok(novagui_system.PasswordScreen('verify').modal, 'same for the password lock')
t.ok(getattr(novagui.ShutdownScreen, 'modal', False),
     'and for shutdown, which comes back only on a deliberate hold')

# ------------------------------------------------------------ the new screens
tz = novagui_system.TZScreen()
start = tz.off
tz.on_event(ev.ROT_CW)
t.eq(tz.off, start + 1, 'turning adjusts the offset')
tz.off = tz.HI
tz.on_event(ev.ROT_CW)
t.eq(tz.off, tz.LO, 'and it wraps at the top rather than running off the end')
tz.off = tz.LO
tz.on_event(ev.ROT_CCW)
t.eq(tz.off, tz.HI, 'and at the bottom')
t.ok(tz.LO <= -12 and tz.HI >= 14, 'the range covers every real civil offset')
tz.off = 3
tz.on_event(ev.SELECT)
t.ok(tz.saved, 'SELECT saves and says so')
import novacore
t.eq(str(novacore.reg('System.TZ_Offset')), '3',
     'writing System.TZ_Offset -- the same key the status bar, the Clock app and '
     'the notification timestamps all read')

vs = novagui_system.VersionsScreen()
labels = [r[0] for r in vs.rows]
for want in ('OS', 'Build', 'NovaD1'):
    t.ok(want in labels, 'the Versions screen reports {}'.format(want))
t.ok(all(isinstance(r[1], str) for r in vs.rows), 'every value is a string')
c = novacanvas.Canvas(128, 64)
vs.draw(c)
t.ok(True, 'and it draws')

# System settings must still fit one screen -- that is the point of the grouping,
# and adding a row is exactly how it gets broken.
t.ok(len(novagui._rows_system()) <= 6,
     'the System group still fits one screen ({} rows)'.format(
         len(novagui._rows_system())))
t.ok(any(r[1] == 'Versions' for r in novagui._rows_system()), 'Versions is in it')
t.ok(any(r[1] == 'Timezone' for r in novagui._rows_clock()),
     'and UTC Offset sits with the other clock settings')

# ------------------------------------------------------- the command footer
cs = novagui.CommandScreen('X', 'true')
cs.lines = ['installed ok', 'restarting']
cs._ok = True
t.ok('OK=home' in cs._footer(), 'a finished command offers one press back to home')
t.ok('done' in cs._footer(), 'and says it is done')
cs._ok = False
t.ok('failed' in cs._footer(), 'a failure is reported as a failure')

# The verdict comes from the shell's own error flag, NOT from scanning the output
# for the word "error". Release notes contain that word all the time, so the text
# scan would have called a successful update failed on exactly the command where
# the verdict matters most.
cs._ok = True
cs.lines = ['Updated OK', 'notes: fixed error handling in wget']
t.ok('done' in cs._footer(),
     'output that merely CONTAINS the word error is still a success')
cs._ok = None
t.ok('finished' in cs._footer(),
     'and with no flag to read it says finished rather than guessing')
import inspect as _ins
t.ok('had_error' in _ins.getsource(novagui.CommandScreen),
     'the verdict is read from RPCortex.had_error -- the same flag && and || use')
t.eq(cs.on_event(ev.SELECT), 'home', 'SELECT on a finished command goes home')
cs2 = novagui.CommandScreen('X', 'true')
t.eq(cs2.on_event(ev.SELECT), None, 'but not while it is still running')

sys.exit(t.done())
