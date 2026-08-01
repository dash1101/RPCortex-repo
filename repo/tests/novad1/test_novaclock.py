# CPU clock control from Settings.
#
# The steps must come from hwinfo's range rather than being invented here: that
# range is the one place the port rules live, and an RP2 below 80 MHz breaks flash
# timing rather than merely running slow. And a change has to do BOTH halves —
# machine.freq() so it takes effect now, Hardware.Boot_Clock so it survives a
# reset. Doing only one is the failure mode that looks like the setting "not
# saving" or "not doing anything".
import sys
import _shims
_shims.install()
from _shims import T

import novapower

t = T('test_novaclock')

steps = novapower.clock_steps()
t.ok(steps, 'there are steps to offer')
t.ok(all(isinstance(s, int) for s in steps), 'they are plain integers')
t.eq(steps, sorted(steps), 'and they are in ascending order')
t.ok(steps[0] >= 80,
     'nothing below 80 MHz is offered -- RP2 flash timing breaks there, it does '
     'not just run slower')
t.ok(len(set(steps)) == len(steps), 'no duplicates')

# ---------------------------------------------------------------- setting it
calls = []
import machine
_real_freq = machine.freq


def fake_freq(*a):
    if a:
        calls.append(a[0])
        fake_freq.cur = a[0]
        return None
    return fake_freq.cur


fake_freq.cur = 150000000
machine.freq = fake_freq

saved = {}
import novacore
_real_save = novacore.save_reg
novacore.save_reg = lambda k, v: saved.__setitem__(k, v)
try:
    target = steps[-1]
    got = novapower.set_clock(target)
    t.eq(calls[-1], target * 1000000, 'machine.freq is called in Hz, not MHz')
    t.eq(got, target, 'the frequency now in effect is returned')
    t.eq(saved.get('Hardware.Boot_Clock'), '{:.1f}MHz'.format(float(target)),
         'the boot clock is persisted in the format Core/post.py parses')
    t.eq(saved.get('Settings.OC_On_Boot'), 'true',
         'and the boot-clock apply is enabled, or post.py would ignore the key')

    # persist=False changes the live clock only.
    saved.clear()
    novapower.set_clock(steps[0], persist=False)
    t.eq(calls[-1], steps[0] * 1000000, 'the live clock still changes')
    t.eq(saved, {}, 'but nothing is written when persist is off')

    # Out-of-range values are refused, and refused BEFORE touching the hardware.
    n = len(calls)
    novapower.set_clock(steps[-1] + 500)
    t.eq(len(calls), n, 'a frequency above the range never reaches machine.freq')
    novapower.set_clock(10)
    t.eq(len(calls), n, 'nor does one below it')
    novapower.set_clock('not a number')
    t.eq(len(calls), n, 'nor does a non-numeric value')

    # A port that rejects the value must leave the registry alone -- persisting a
    # frequency the hardware refused would brick the next boot.
    saved.clear()

    def refusing(*a):
        if a:
            raise ValueError('unsupported frequency')
        return 150000000

    machine.freq = refusing
    novapower.set_clock(steps[-1])
    t.eq(saved, {},
         'a refused frequency is not persisted -- it would be applied at boot and '
         'fail there too, with no shell to undo it')
finally:
    machine.freq = _real_freq
    novacore.save_reg = _real_save

# --------------------------------------------------------------- the settings row
import novagui

row = novagui._clock_row()
t.eq(row[0], 'cycle', 'the clock row is a cycle row')
t.eq(row[1], 'CPU MHz', 'labelled for what it is')
t.eq(row[2], None,
     'the clock row stores NOTHING -- three things move this number (this row, '
     '`pulse set`, and Dyn Clock dropping to the idle floor) and a stored '
     'preference would only ever track one of them')
t.eq(row[3], [str(s) for s in steps], 'offering exactly the platform steps')
t.ok(callable(row[4]), 'its value is a live read, not a constant')
t.ok(row[5] is not None, 'and it has an apply callback, or turning it would do nothing')

# The settings screen must render a computed row from that callable, and must not
# try to write to a None key when the row is turned.
scr = novagui.SettingsScreen('Clock', novagui._rows_clock())
machine.freq = fake_freq
fake_freq.cur = 133000000
try:
    t.eq(scr._val(row), '133',
         'the row reports the frequency the board is actually running')
    fake_freq.cur = 80000000
    t.eq(scr._val(row), '80', 'and follows it when something else changes it')
finally:
    machine.freq = _real_freq

# A computed row whose getter raises must not take the settings screen down.
t.eq(scr._val(('cycle', 'X', None, ['a'], lambda: 1 / 0, None)), '?',
     'a failing live read shows ? rather than raising into the draw loop')

# Grouping: System must still be one screen. That is the whole point of the
# grouped settings layout, and adding a row is exactly how it gets broken.
sysrows = novagui._rows_system()
t.ok(len(sysrows) <= 6, 'the System group still fits one screen ({} rows)'.format(len(sysrows)))
t.ok(any(r[1] == 'Clock' for r in sysrows), 'System has a Clock group')
clockrows = novagui._rows_clock()
t.ok(any(r[1] == 'CPU MHz' for r in clockrows), 'which contains the CPU speed row')
t.ok(any(r[1] == 'Dyn Clock' for r in clockrows),
     'and the dynamic clock, which overrides it -- the two belong together')

sys.exit(t.done())
