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
