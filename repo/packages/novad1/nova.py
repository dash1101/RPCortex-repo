# Desc: Nova D1 scripting API — what scripts + button-grid apps call to DO things.
# File: /Packages/NovaD1/nova.py
#
# A Python script (or a declarative button-grid) drives the device through this:
#   import nova
#   nova.ir_send('tv.ir', 'Power'); nova.lora_send('hi'); nova.notify('done')
#   nova.subghz_send('gate.sub'); nova.run('sysinfo'); nova.sleep(0.5)
# Declarative button grids use action strings ('ir tv.ir Power', 'lora hi', ...)
# dispatched by do(). Everything is guarded so a bad call can't crash the UI.
# MicroPython-safe: no f-strings, positional split, .format() only.

import sys


def notify(text):
    try:
        import novanotify
        return novanotify.notify(str(text))
    except Exception:
        return False


def log(msg):
    try:
        import novalog
        novalog.log(str(msg))
    except Exception:
        pass


def sleep(s):
    try:
        import utime
        utime.sleep(float(s))
    except Exception:
        pass


def read_code(cat, name):
    import novastore
    return novastore.read_code(cat, name)


def save_code(cat, name, text):
    import novastore
    return novastore.save_code(cat, name, text)


def list_codes(cat):
    """List saved code/data file names in a Nova store category (ir/subghz/nfc/
    lora/scripts/… or an app's own). Companion to read_code/save_code."""
    import novastore
    try:
        return novastore.list_codes(cat)
    except Exception:
        return []


def run(cmd):
    """Run an OS shell command (side effects). Returns True if dispatched."""
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
    if lp is None or not hasattr(lp, '_run_line'):
        return False
    try:
        lp._run_line(str(cmd))
        return True
    except Exception:
        return False


def ir_send(fname, signal=None):
    """Replay an IR signal from a saved .ir file (by name, or the first signal)."""
    import novastore
    import novair
    txt = novastore.read_code('ir', fname)
    if not txt:
        return False
    sigs = novair.parse_flipper(txt)
    if not sigs:
        return False
    target = sigs[0]
    if signal:
        for s in sigs:
            if s[0] == signal:
                target = s
                break
    n, fr, du, times = target
    novair.replay(times, fr, du)
    return True


def ir_send_raw(times, freq=38000, duty=0.33):
    import novair
    novair.replay(times, freq, duty)
    return True


def lora_send(text):
    import novamsg
    return novamsg.send(str(text))


def subghz_send(fname):
    import novastore
    import novacc
    txt = novastore.read_code('subghz', fname)
    if not txt:
        return False
    return novacc.fire_text(txt)


def nfc_read():
    import novamods
    return novamods.pn532_read_uid()


def ble_ping(platform='apple', model=None, secs=8):
    """Broadcast a 'device nearby' pairing advertisement (Apple/iOS or Android Fast
    Pair) for a bounded time — the Flipper-style BLE ping, runnable from a script so
    cross-tool ping scripts port to the D1. Point it at your own phone."""
    import novable
    return novable.ping(platform, model, secs)


def ble_scan(secs=5):
    import novable
    return novable.scan(int(secs * 1000))


def led(r, g, b):
    """Set the status LED (WS2812, or plain on/off in gpio mode) to an (r,g,b)
    colour. Best-effort; returns True on success. For a flashlight, torch apps, etc."""
    try:
        import novamods
        return novamods.set_led(int(r) & 0xff, int(g) & 0xff, int(b) & 0xff)
    except Exception:
        return False


def led_off():
    return led(0, 0, 0)


def beep(freq=2000, ms=80):
    """A short buzzer beep (PWM) at freq Hz for ms milliseconds. Best-effort; never
    raises. For timers, metronomes, key-press feedback. Buzzer pin from
    Apps.NovaD1_PIN_buzzer (default 40)."""
    try:
        import machine
        import utime
        import novacore
        pin = int(novacore.reg('Apps.NovaD1_PIN_buzzer', 40) or 40)
    except Exception:
        return False
    pwm = None
    try:
        pwm = machine.PWM(machine.Pin(pin))
        pwm.freq(int(freq))
        pwm.duty_u16(18000)
        utime.sleep_ms(int(ms))
        pwm.duty_u16(0)
        return True
    except Exception:
        return False
    finally:
        try:
            if pwm is not None:
                pwm.duty_u16(0)
                pwm.deinit()
        except Exception:
            pass


def do(action):
    """Execute a button-grid action string. Returns a short status string."""
    a = (action or '').strip().split(None, 1)
    if not a:
        return 'empty'
    cmd = a[0].lower()
    arg = a[1].strip() if len(a) > 1 else ''
    try:
        if cmd == 'ir':
            p = arg.split(None, 1)
            ok = ir_send(p[0], p[1] if len(p) > 1 else None) if p else False
            return 'IR sent' if ok else 'IR failed'
        if cmd == 'lora':
            lora_send(arg)
            return 'LoRa sent'
        if cmd == 'subghz':
            return 'SubGHz sent' if subghz_send(arg) else 'SubGHz failed'
        if cmd == 'ble':
            # 'ble ping apple airpods' / 'ble ping android headphones' / 'ble scan'
            p = arg.split()
            if p and p[0] == 'scan':
                return 'BLE: {} devices'.format(len(ble_scan()))
            sub = p[1] if len(p) > 1 else 'apple'      # platform
            mdl = p[2] if len(p) > 2 else None         # model
            return 'BLE ping ' + str(ble_ping(sub, mdl))
        if cmd == 'led':
            # 'led 120 0 0' (r g b) or 'led off'
            p = arg.split()
            if p and p[0].lower() == 'off':
                led_off()
                return 'led off'
            v = [int(x) for x in p[:3]] + [0, 0, 0]
            led(v[0], v[1], v[2])
            return 'led set'
        if cmd == 'beep':
            # 'beep' or 'beep 1500' or 'beep 1500 120'
            p = arg.split()
            beep(int(p[0]) if p else 2000, int(p[1]) if len(p) > 1 else 80)
            return 'beep'
        if cmd == 'notify':
            notify(arg)
            return 'notified'
        if cmd == 'run':
            run(arg)
            return 'ran'
        if cmd == 'sleep':
            sleep(arg or '0.2')
            return 'slept'
        if cmd == 'log':
            log(arg)
            return 'logged'
    except Exception:
        return 'error'
    return 'unknown: ' + cmd


def parse_buttons(text):
    """Parse a button-grid script -> (title, [(label, action), ...]).
    Format: 'title: My Remote' + lines 'Label = action args' (# = comment)."""
    title = 'Script'
    btns = []
    for line in (text or '').split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        low = line.lower()
        if low.startswith('title:'):
            title = line.split(':', 1)[1].strip() or title
            continue
        if '=' in line:
            lbl, act = line.split('=', 1)
            lbl = lbl.strip()
            act = act.strip()
            if lbl and act:
                btns.append((lbl, act))
    return title, btns


def run_py(text):
    """Run a Python script with the nova API in scope. Returns (ok, error_str)."""
    import nova as _n
    g = {'nova': _n, '__name__': '__main__'}
    try:
        exec(text, g)
        return True, ''
    except Exception as e:
        return False, str(e)
