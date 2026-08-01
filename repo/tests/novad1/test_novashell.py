# Shell screen: the RPCortex shell rendered on the panel.
#
# Two things here are worth guarding. The scrollback is a FIXED ring — an
# unbounded transcript on a non-compacting heap is a slow leak that only shows
# after a long session, which is the hardest kind to attribute. And the control
# scheme is unusual (hold SELECT to type, tap SELECT for Enter), so it is asserted
# rather than left to whoever next edits on_event.
import sys
import _shims
_shims.install()
from _shims import T

import novacanvas
import novainput as ev
import novagui_shell as S

t = T('test_novashell')

c = novacanvas.Canvas(128, 64)

# ------------------------------------------------------------ the scrollback ring
s = S.ShellScreen()
for i in range(S._MAX_LINES * 3):
    s._emit('line {}'.format(i))
t.eq(len(s.lines), S._MAX_LINES,
     'the scrollback is capped -- an unbounded transcript would leak on a heap '
     'that never compacts')
t.eq(s.lines[-1], 'line {}'.format(S._MAX_LINES * 3 - 1),
     'the NEWEST line survives; it is the front that is dropped')
t.ok('line 0' not in s.lines, 'the oldest lines are gone')

# One over the cap must drop exactly one, not rebuild the list every append.
s2 = S.ShellScreen()
s2.lines = ['x'] * S._MAX_LINES
s2._emit('new')
t.eq(len(s2.lines), S._MAX_LINES, 'still exactly at the cap')
t.eq(s2.lines[-1], 'new', 'and the new line is last')

# ---------------------------------------------------------------- the controls
s = S.ShellScreen()

# HOLD SELECT opens the keyboard, pre-filled with anything half-typed.
s.pending = 'sysin'
kb = s.on_event(ev.SELECT_HOLD)
t.ok(kb is not None, 'holding SELECT returns a screen (the keyboard)')
t.eq(kb.__class__.__name__, 'KeyboardScreen', 'and it is the keyboard')
t.eq(getattr(kb, 'text', ''), 'sysin',
     'the keyboard opens pre-filled, so a long command need not be retyped')

# A short SELECT is Enter: it queues the command and echoes it.
s = S.ShellScreen()
s.pending = 'sysinfo'
n_before = len(s.lines)
t.eq(s.on_event(ev.SELECT), None, 'a tap does not leave the screen')
t.eq(s.pending, '', 'the pending line is consumed')
t.eq(s._busy, 'sysinfo', 'and the command is queued, not run inside on_event')
t.ok(len(s.lines) > n_before, 'the command is echoed into the transcript')
t.ok(any(S._PROMPT in ln for ln in s.lines), 'echoed with the prompt marker')

# An empty Enter does nothing at all -- no blank echo, no queued no-op.
s3 = S.ShellScreen()
n = len(s3.lines)
s3.on_event(ev.SELECT)
t.eq(s3._busy, None, 'Enter on an empty line queues nothing')
t.eq(len(s3.lines), n, 'and adds no blank row')

# HOME quits, as asked for.
t.eq(S.ShellScreen().on_event(ev.HOME), ev.HOME, 'HOME leaves the app')

# BACK clears a half-typed command first, and only leaves once there is none.
s4 = S.ShellScreen()
s4.pending = 'reboo'
t.eq(s4.on_event(ev.BACK), None, 'BACK with text pending stays')
t.eq(s4.pending, '', 'and clears it')
t.eq(s4.on_event(ev.BACK), ev.BACK, 'BACK again leaves')

# --------------------------------------------------------------- paint-then-run
# The shell call is synchronous and can take seconds. One frame has to reach the
# panel before it blocks, or the echoed line is still queued when the loop stalls
# and the device looks dead.
s5 = S.ShellScreen()
s5.pending = 'anything'
s5.on_event(ev.SELECT)
t.ok(s5.tick(16), 'the first tick asks for a repaint')
t.eq(s5._busy, 'anything', 'and has NOT run the command yet')
s5.tick(16)
t.eq(s5._busy, None, 'the second tick runs it')

# ------------------------------------------------------------------- scrolling
s6 = S.ShellScreen()
for i in range(30):
    s6._emit('l{}'.format(i))
s6.draw(c)
t.ok(s6._follow, 'a fresh screen follows the newest output')
s6.on_event(ev.ROT_CCW)
t.ok(not s6._follow, 'scrolling back detaches from the tail')
s6.top = 0
s6.on_event(ev.ROT_CCW)
t.eq(s6.top, 0, 'scrolling up at the top does not go negative')

# --------------------------------------------------------------- no shell, no crash
# On the host there is no launchpad in sys.modules, which is the same situation as
# a build where the shell is unavailable. It must report that, not raise.
out = S.run_line('sysinfo')
t.ok(isinstance(out, list), 'run_line always returns a list')
t.ok(out and 'not available' in out[0],
     'with no shell loaded it says so rather than raising')

# ------------------------------------------------- the runner delivers the hold
# on_event(SELECT_HOLD) working proves the handler, not that anything ever sends
# that event. NovaUI.handle intercepts HOME_HOLD as a global escape and passes
# everything else to the top screen -- if SELECT_HOLD were swallowed the same way,
# the keyboard would be unreachable and this suite would still be green.
import novacanvas as _nc
import novagui
import display


class _Spy:
    title = 'spy'
    def __init__(self): self.got = []
    def draw(self, c): pass
    def on_event(self, e): self.got.append(e); return None


spy = _Spy()
ui = novagui.NovaUI(display.MockDisplay(128, 64), _nc.Canvas(128, 64),
                    ev.ScriptedSource(), {}, spy)
ui.handle(ev.SELECT_HOLD)
t.ok(ev.SELECT_HOLD in spy.got,
     'the runner passes SELECT_HOLD through to the top screen')
ui.handle(ev.SELECT)
t.ok(ev.SELECT in spy.got, 'and a plain SELECT too')

# novainput must actually emit it, or nothing above matters on real hardware.
import inspect as _insp
import novainput
isrc = _insp.getsource(novainput)
t.ok('_pending.append(SELECT_HOLD)' in isrc,
     'novainput queues SELECT_HOLD when SELECT is held')
t.ok('reported on release' in isrc or 'a tap -> reported on release' in isrc,
     'SELECT reports on RELEASE, which is what lets a hold be told from a tap '
     'without firing both')

# The prompt row must be reserved: the pending command stays visible however far
# the transcript is scrolled.
t.ok(s6._visible(c) < (c.h - S._TOP) // S._ROWH,
     'one row is held back for the prompt')

s6.pending = 'x' * 200
s6.draw(c)          # must not raise on an over-long command
t.ok(True, 'an over-long pending command draws without raising')

sys.exit(t.done())
