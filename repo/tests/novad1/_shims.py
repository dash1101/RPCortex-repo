# Shared test shims + a tiny harness for the Nova D1 package tests.
# Runs the REAL package modules under CPython with the hardware stubbed, so the
# parsers / encoders / format logic are tested with zero hardware + zero deps
# (plain `python3 test_x.py`, or `python3 run_all.py`). Matches the project's
# standalone-test-script convention.
import sys
import os
import types
import time as _t

_REG = {}


def set_reg(d):
    _REG.clear()
    _REG.update(d or {})


def install():
    """Stub MicroPython/hardware modules + put the novad1 package on sys.path."""
    if 'machine' not in sys.modules:
        m = types.ModuleType('machine')

        class Pin:
            OUT = 1; IN = 0; PULL_UP = 2
            def __init__(s, *a, **k): pass
            def value(s, *a): return 0
            def irq(s, *a, **k): pass

        class I2C:
            def __init__(s, *a, **k): pass
            def scan(s): return []
            def writeto(s, *a, **k): pass
            def readfrom(s, *a, **k): return b'\x00' * 32

        class SPI:
            def __init__(s, *a, **k): pass
            def write(s, *a): pass
            def read(s, n, *a): return b'\x00' * n
            def deinit(s): pass

        m.Pin = Pin; m.I2C = I2C; m.SPI = SPI
        m.RTC = lambda *a: types.SimpleNamespace(datetime=lambda *a: (2026, 6, 30, 0, 12, 30, 0, 0))
        m.freq = lambda *a: 240000000
        sys.modules['machine'] = m
        sys.modules['network'] = types.SimpleNamespace(
            WLAN=lambda *a: types.SimpleNamespace(active=lambda *a: False, scan=lambda: [],
                                                  isconnected=lambda: False, status=lambda *a: 0),
            STA_IF=0)
        sys.modules['utime'] = types.SimpleNamespace(
            ticks_ms=lambda: int(_t.time() * 1000), ticks_us=lambda: int(_t.time() * 1e6),
            ticks_diff=lambda a, b: a - b, ticks_add=lambda a, b: a + b,
            sleep_ms=lambda ms: None, sleep_us=lambda us: None,
            time=lambda: int(_t.time()), localtime=lambda *a: _t.localtime(*(a or ())))
        # remove() and mkdir() are REAL. A no-op stub silently passes tests the
        # device would fail: temp-file cleanup, and creating a directory that
        # does not exist yet.
        sys.modules['uos'] = types.SimpleNamespace(
            urandom=os.urandom, listdir=lambda p='.': [],
            stat=lambda p: (_ for _ in ()).throw(OSError), mkdir=os.mkdir,
            remove=os.remove)
        sys.modules['regedit'] = types.SimpleNamespace(
            read=lambda k: _REG.get(k), save=lambda k, v: _REG.__setitem__(k, v) or True)

        # A minimal RPCortex. The OS-level radio lock lives there, and without a
        # stub every `import RPCortex` in package code fails into its except
        # branch — so a test would silently pass while the lock never engaged.
        def _radio_locked():
            return str(_REG.get('Settings.Radio_Lock') or 'off').lower() in (
                'on', 'true', '1')

        def _lock_radios(on=True):
            _REG['Settings.Radio_Lock'] = 'on' if on else 'off'
            return True

        sys.modules['RPCortex'] = types.SimpleNamespace(
            radio_locked=_radio_locked, lock_radios=_lock_radios,
            _radios_down=lambda: None,
            OS_VERSION='v1.0.0', OS_CODENAME='RPCortex Vela',
            storage_state=lambda p='/': (10, 'ok'),
            reserve_state=lambda: (False, 0))
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        '..', '..', 'packages', 'novad1'))


class T:
    """Minimal assert harness: t.ok(cond, label); sys.exit(t.done())."""
    def __init__(self, name):
        self.name = name
        self.p = 0
        self.f = 0

    def ok(self, cond, label):
        if cond:
            self.p += 1
        else:
            self.f += 1
            print('  FAIL: ' + label)

    def eq(self, a, b, label):
        self.ok(a == b, '{} (got {!r}, want {!r})'.format(label, a, b))

    def done(self):
        print('{}: {}/{} passed'.format(self.name, self.p, self.p + self.f))
        return 1 if self.f else 0
