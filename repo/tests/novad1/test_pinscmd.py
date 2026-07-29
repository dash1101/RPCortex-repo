# The `d1 pins` / `d1 display` command surface. This exists so wiring a Nova D1 never
# needs `reg set Apps.NovaD1_PIN_*` by hand, so the tests care about two things: the
# registry side effects are right, and the output tells you where a value came from.
import sys
import io
import _shims
_shims.install()
from _shims import T
import novad1
import novaboard

t = T('test_pinscmd')


def run(cmd):
    """Run a novad1 subcommand, returning everything it printed."""
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        novad1.novad1(cmd)
    finally:
        sys.stdout = real
    return buf.getvalue()

# ------------------------------------------------------------------ the listing
_shims.set_reg({})
out = run('pins')
t.ok('ir_tx' in out and '39' in out, 'lists a pin with its resolved value')
t.ok('board' in out, 'marks profile-sourced pins')
t.ok('IR LED' in out, 'explains what the pin is for')
t.ok('esp32s3' in out, 'names the active board')
for name in novaboard.names():
    t.ok(name in out, 'listing includes {}'.format(name))
t.ok('unset' in out, 'shows opt-in pins as unset rather than hiding them')

# The source column is the point: a default and something you set months ago must
# not look identical.
_shims.set_reg({'Apps.NovaD1_PIN_ir_tx': '12'})
out = run('pins')
t.ok('override' in out, 'an overridden pin is labelled as such')
t.ok('overridden' in out, 'and the summary line counts overrides')

# --------------------------------------------------------------------- set/clear
_shims.set_reg({})
out = run('pins set ir_tx 12')
t.eq(novaboard.pin('ir_tx'), 12, 'set applies the new pin')
t.ok('was 39' in out, 'and reports what it replaced')
t.ok('clear ir_tx' in out, 'and how to undo it')

# Re-setting an already-overridden pin must report the value that was actually in
# effect, not the board default -- otherwise "was 39" is a lie about a pin at 12.
out = run('pins set ir_tx 20')
t.ok('was 12' in out, 'reports the previous OVERRIDE, not the board default')
t.ok('was 39' not in out, 'and does not report the board default it never had')

out = run('pins clear ir_tx')
t.eq(novaboard.pin('ir_tx'), 39, 'clear reverts to the board default')

# An opt-in pin has no previous value at all; say so rather than printing None.
out = run('pins set battery 1')
t.ok('was unset' in out, 'an unset pin reports "was unset"')
novaboard.clear_pin('battery')

out = run('pins set ir_tx notanumber')
t.ok('not a valid pin' in out, 'rejects a non-numeric pin')
t.eq(novaboard.pin('ir_tx'), 39, 'and leaves the value untouched')

out = run('pins set banana 5')
t.ok('Unknown pin' in out, 'rejects an unknown pin name')
t.ok('d1 pins' in out, 'and points at the listing')

# ----------------------------------------------------------------- board switch
_shims.set_reg({})
out = run('pins board')
for b in ('esp32s3', 'pico2w', 'picoplus2w'):
    t.ok(b in out, 'board listing includes {}'.format(b))
t.ok('*' in out, 'marks the active one')
t.ok('draft' in out.lower(), 'flags draft profiles as such, not as ready')
t.ok('pins used' in out, 'shows the pin budget per board')

out = run('pins board pico2w')
t.eq(novaboard.board(), 'pico2w', 'switches board')
t.ok('consistent' in out or 'problem' in out, 'validates immediately after switching')

# The legacy id must still work from the command line, and report the canonical name.
_shims.set_reg({})
out = run('pins board rp2350')
t.eq(novaboard.board(), 'pico2w', "the old 'rp2350' id still switches, to pico2w")
t.ok('pico2w' in out, 'and the confirmation names the canonical board')

out = run('pins board nonsense')
t.ok('Unknown board' in out, 'rejects an unknown board')
t.eq(novaboard.board(), 'pico2w', 'and does not change the active board')

# 'auto' has to fail with a useful message on a host it cannot identify, not crash.
out = run('pins board auto')
t.ok('identify' in out.lower(), "'auto' explains itself when detection fails")

# ---------------------------------------------------------------------- check
_shims.set_reg({})
out = run('pins check')
t.ok('consistent' in out, 'a clean profile reports consistent')

# A real problem has to surface, or check() is decoration.
novaboard._PROFILES['_bad'] = {'name': 'bad', 'mcu': 'rp2350',
                               'reserved': (25,), 'pins': {'led': 25, 'dht': 25}}
_shims.set_reg({'Apps.NovaD1_Board': '_bad'})
out = run('pins check')
t.ok('problem' in out.lower(), 'a broken profile reports problems')
t.ok('reserved' in out, 'and names the reserved-GPIO problem')
t.ok('used by both' in out, 'and the duplicate-pin problem')
del novaboard._PROFILES['_bad']

# --------------------------------------------------------------------- display
_shims.set_reg({})
out = run('display')
for k in ('sh1106', 'ssd1306', 'ssd1309'):
    t.ok(k in out, 'display listing offers {}'.format(k))
t.ok('mock' not in out, 'the host-only mock backend is not offered on-device')

out = run('display ssd1309')
t.eq(_shims._REG.get('Apps.NovaD1_Display'), 'ssd1309', 'display selection persists')
out = run('display wat')
t.ok('Unknown panel' in out, 'rejects an unknown panel')
t.eq(_shims._REG.get('Apps.NovaD1_Display'), 'ssd1309', 'and keeps the previous choice')

# ------------------------------------------------------- discoverability
_shims.set_reg({})
out = run('help')
t.ok('pins' in out, 'help mentions pins')
t.ok('display' in out, 'help mentions display')
t.ok('reg set' not in out, 'help no longer tells people to edit the registry')

out = run('status')
t.ok('Board' in out, 'status reports the active board')
t.ok('overrides' in out, 'status reports which pins were overridden')

sys.exit(t.done())
