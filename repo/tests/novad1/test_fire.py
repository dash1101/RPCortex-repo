# novad1 fire: presence-gate the radios. Firing a Sub-GHz/LoRa code when the CC1101/
# SX1276 isn't connected must fail fast with a clear message (shell + web share this
# path), not fire blind. Hardware stubbed.
import sys
import types
import _shims
_shims.install()
from _shims import T
import novad1 as ND
import novastore

t = T('test_fire')
novastore.read_code = lambda cat, name: 'RAW_Data: 100 -100\n' if name else None
_noop = lambda *a, **k: None


def run(arg):
    """Drive _fire capturing (ok_msgs, err_msgs)."""
    oks, errs = [], []
    ND._fire(_noop, lambda *a, **k: oks.append(a[0]), _noop,
             lambda *a, **k: errs.append(a[0]), _noop, arg)
    return oks, errs


# Sub-GHz absent -> blocked with a clear message, nothing fired
sys.modules['novacc'] = types.SimpleNamespace(present=lambda: False, fire_text=lambda x: True)
oks, errs = run('subghz test')
t.ok(any('not detected' in e.lower() for e in errs), 'subghz blocked when CC1101 absent')
t.ok(not oks, 'nothing fired when subghz absent')

# Sub-GHz present -> fires
sys.modules['novacc'] = types.SimpleNamespace(present=lambda: True, fire_text=lambda x: True)
oks, errs = run('subghz test')
t.ok(any('fired' in o.lower() for o in oks), 'subghz fires when CC1101 present')

# LoRa absent -> blocked
sys.modules['novamsg'] = types.SimpleNamespace(present=lambda: False, send=_noop)
oks, errs = run('lora hello')
t.ok(any('not detected' in e.lower() for e in errs), 'lora blocked when SX1276 absent')
t.ok(not oks, 'nothing fired when lora absent')

# LoRa present -> fires
sys.modules['novamsg'] = types.SimpleNamespace(present=lambda: True, send=_noop)
oks, errs = run('lora hello')
t.ok(any('fired' in o.lower() for o in oks), 'lora fires when SX1276 present')

# unknown code -> clear error
oks, errs = run('subghz __nope__')
novastore.read_code = lambda cat, name: None
oks, errs = run('subghz missing')
t.ok(any('no such code' in e.lower() for e in errs), 'missing code reports clearly')

sys.exit(t.done())
