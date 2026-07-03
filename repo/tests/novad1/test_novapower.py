# novapower: battery %, USB detect, low-flag — reads ONLY when the pin is configured
# (an unwired ADC must never lie). Battery math tested via a stubbed ADC.
import sys
import _shims
_shims.install()
from _shims import T
import novapower as P

t = T('test_novapower')


def _stub_adc(volts_at_pin):
    """Make machine.ADC report a fixed pin voltage (pre-divider)."""
    import machine
    raw = int(volts_at_pin / 3.3 * 65535)

    class ADC:
        ATTN_11DB = 3
        def __init__(self, pin):
            pass
        def atten(self, x):
            pass
        def read_u16(self):
            return raw
    machine.ADC = ADC


# No pins configured -> nothing is claimed (the anti-lying guarantee)
_shims.set_reg({})
d = P._read_raw()
t.ok(not d['have'], 'no battery pin -> have=False')
t.eq(d['usb'], None, 'no vbus pin -> usb unknown')
t.ok(not d['low'], 'no data -> not low')

# A plausible 3.75 V pack (divider 2.0 -> 1.875 V at the pin) -> ~50%
_stub_adc(1.875)
_shims.set_reg({'Apps.NovaD1_PIN_battery': '4', 'Apps.NovaD1_BattDiv': '2.0'})
d = P._read_raw()
t.ok(d['have'], 'configured + plausible -> have=True')
t.ok(48 <= d['pct'] <= 52, 'mid pack ~50% (got {})'.format(d['pct']))
t.ok(abs(d['volts'] - 3.75) < 0.05, 'reports pack voltage')

# An implausible reading (floating input) is rejected
_stub_adc(3.0)                              # *2.0 = 6.0 V, outside 2.5..4.6
d = P._read_raw()
t.ok(not d['have'], 'implausible voltage -> have=False (no lying icon)')

# Low-battery flag: below threshold, not on USB
_stub_adc(1.70)                             # *2 = 3.4 V -> ~11%
_shims.set_reg({'Apps.NovaD1_PIN_battery': '4', 'Apps.NovaD1_BattDiv': '2.0', 'Apps.NovaD1_LowPct': '15'})
d = P._read_raw()
t.ok(d['have'] and d['pct'] < 15, 'low pack reads low pct')
t.ok(d['low'], 'low flag set when below threshold + not on USB')

# read() caches (second call within 5s returns the same dict object)
P._cache['d'] = None
P._cache['t'] = None
a = P.read()
b = P.read()
t.ok(a is b, 'read() caches within the window')

sys.exit(t.done())
