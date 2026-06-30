#!/usr/bin/env python3
# Nova D1 DESKTOP SIMULATOR — run the REAL Nova GUI on your computer, no hardware.
#
# Renders the 128x64 OLED to your terminal (unicode half-blocks) and drives it with
# the arrow keys, so you can test menus / apps / flows / layouts without the device.
#
#     Up / Left   = rotate encoder CCW (previous)
#     Down / Right = rotate encoder CW (next)
#     Enter = Select     Backspace/Esc = Back     h = Home     q = Quit
#
# Hardware apps (NFC / GPS / Sub-GHz / BLE ...) open but report "not found" (there
# are no real chips) — you're testing the UI/UX, not the radios. The GUI code is the
# exact same code that runs on the device.
#
# Usage:  python3 sim.py            (interactive — Unix/macOS terminal; Windows: WSL)
#         python3 sim.py --demo     (scripted walkthrough, prints frames; no keyboard)
#
import sys
import os
import time
import types

# --- stub the MicroPython / hardware modules so the GUI is navigable on a PC ----
_t = time


def _install_stubs():
    m = types.ModuleType('machine')

    class Pin:
        OUT = 1
        IN = 0
        PULL_UP = 2

        def __init__(self, *a, **k):
            pass

        def value(self, *a):
            return 0

        def irq(self, *a, **k):
            pass

    class I2C:
        def __init__(self, *a, **k):
            pass

        def scan(self):
            return []

        def writeto(self, *a, **k):
            pass

        def readfrom(self, *a, **k):
            return b'\x00' * 32

    class SPI:
        def __init__(self, *a, **k):
            pass

        def write(self, *a):
            pass

        def read(self, n, *a):
            return b'\x00' * n

        def deinit(self):
            pass

    m.Pin = Pin
    m.I2C = I2C
    m.SPI = SPI
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
    sys.modules['uos'] = types.SimpleNamespace(
        urandom=os.urandom, listdir=lambda p='.': [],
        stat=lambda p: (_ for _ in ()).throw(OSError), mkdir=lambda p: None)
    _reg = {'System.TZ_Offset': '0', 'Apps.NovaD1_Contrast': '255',
            'Apps.NovaD1_DimSec': '0', 'Apps.NovaD1_OffSec': '0'}
    sys.modules['regedit'] = types.SimpleNamespace(
        read=lambda k: _reg.get(k), save=lambda k, v: _reg.__setitem__(k, v) or True)
    # no 'bluetooth' module -> novable.available() is False (BLE app says "no BLE")


_install_stubs()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'packages', 'novad1'))
import novacanvas      # noqa: E402
import display         # noqa: E402
import novagui         # noqa: E402
import novainput as ev  # noqa: E402

_W, _H = 128, 64


def _frame(buf):
    """MONO_VLSB buffer -> terminal string (2 vertical px per char via half-blocks)."""
    rows = ['  +' + '-' * _W + '+']
    for y in range(0, _H, 2):
        line = ['  |']
        for x in range(_W):
            top = buf[(y >> 3) * _W + x] & (1 << (y & 7))
            bot = (buf[((y + 1) >> 3) * _W + x] & (1 << ((y + 1) & 7))) if y + 1 < _H else 0
            line.append('█' if top and bot else '▀' if top else '▄' if bot else ' ')
        rows.append(''.join(line) + '|')
    rows.append('  +' + '-' * _W + '+')
    return '\n'.join(rows)


def _build():
    cv = novacanvas.Canvas(_W, _H)
    mk = display.MockDisplay(_W, _H)
    state = {'wifi': 'connected', 'time': '12:30', 'notify': 0, 'saving': False, 'power': {}}
    src = types.SimpleNamespace(poll=lambda: None)
    ui = novagui.NovaUI(mk, cv, src, state, novagui.build_home({}))
    return ui, mk


def _settle(ui, draw):
    """Render + run a few animation ticks so slides/cooperative screens play out."""
    for _ in range(14):
        ui.render()
        draw()
        scr = ui.stack[-1]
        more = False
        try:
            more = scr.tick(20)
        except Exception:
            pass
        if not getattr(scr, 'animating', lambda: False)():
            ui.render()
            draw()
            break
        time.sleep(0.03)


def run_interactive():
    import termios
    import tty
    import select as _sel
    ui, mk = _build()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    keymap = {'\x1b[A': ev.ROT_CCW, '\x1b[D': ev.ROT_CCW, '\x1b[B': ev.ROT_CW,
              '\x1b[C': ev.ROT_CW, '\r': ev.SELECT, '\n': ev.SELECT,
              '\x7f': ev.BACK, '\x08': ev.BACK}

    def draw():
        sys.stdout.write('\x1b[H\x1b[2J' + _frame(mk.last) +
                         '\n  Up/Dn=turn  Enter=select  Bksp=back  h=home  q=quit\n')
        sys.stdout.flush()

    try:
        tty.setraw(fd)
        ui.render()
        draw()
        while True:
            ch = sys.stdin.read(1)
            if ch in ('q', '\x03'):
                break
            if ch == 'h':
                ui._apply('home')
                _settle(ui, draw)
                continue
            if ch == '\x1b':
                r, _, _ = _sel.select([sys.stdin], [], [], 0.02)
                if r:
                    ch += sys.stdin.read(2)
                else:
                    ui.handle(ev.BACK)
                    _settle(ui, draw)
                    continue
            e = keymap.get(ch)
            if e is not None:
                ui.handle(e)
                _settle(ui, draw)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write('\x1b[2J\x1b[H')
        sys.stdout.flush()


def run_demo():
    """No keyboard: drive a scripted tour, printing frames — for CI / a quick look."""
    ui, mk = _build()
    script = [('home', None)] + [('rot', ev.ROT_CW)] * 3 + [('sel', ev.SELECT),
                                                            ('back', ev.BACK),
                                                            ('rot', ev.ROT_CW), ('sel', ev.SELECT)]
    ui.render()
    print('=== Nova D1 simulator (demo tour) ===')
    print(_frame(mk.last))
    for label, e in script:
        if e is not None:
            ui.handle(e)
        for _ in range(10):
            ui.render()
            scr = ui.stack[-1]
            try:
                scr.tick(20)
            except Exception:
                pass
            if not getattr(scr, 'animating', lambda: False)():
                break
        ui.render()
        print('\n--- after %s -> %s ---' % (label, getattr(ui.stack[-1], 'title', '?')))
        print(_frame(mk.last))


if __name__ == '__main__':
    if '--demo' in sys.argv:
        run_demo()
    else:
        try:
            run_interactive()
        except Exception as e:
            print('interactive mode needs a Unix/macOS terminal (%s).' % e)
            print('Try:  python3 sim.py --demo')
