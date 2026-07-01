# Scripting API: button-grid parsing + the do() action dispatcher.
import sys
import types
import _shims
_shims.install()
from _shims import T
import nova

t = T('test_nova')

# --- parse_buttons ---
title, btns = nova.parse_buttons(
    "title: My Remote\n# a comment\nPower = ir tv.ir Power\nHi = lora hello\n\nGate = subghz gate.sub\n")
t.eq(title, 'My Remote', 'button grid title')
t.eq(len(btns), 3, 'three buttons (comment/blank skipped)')
t.eq(btns[0], ('Power', 'ir tv.ir Power'), 'first button label+action')
t.eq(btns[1], ('Hi', 'lora hello'), 'second button')

# --- do() dispatch (mock the effect modules so nothing hits hardware) ---
fired = []
sys.modules['novable'] = types.SimpleNamespace(
    ping=lambda platform='apple', model=None, secs=8: (fired.append(('ble', platform, model)) or model or 'airpods'),
    scan=lambda ms=5000: [])
sys.modules['novanotify'] = types.SimpleNamespace(notify=lambda x: fired.append(('notify', x)))
sys.modules['novalog'] = types.SimpleNamespace(log=lambda x: fired.append(('log', x)))

t.eq(nova.do(''), 'empty', 'empty action')
t.ok(nova.do('notify hello').startswith('notif') and ('notify', 'hello') in fired, 'do notify')
t.eq(nova.do('sleep 0'), 'slept', 'do sleep')
r = nova.do('ble ping android headphones')
t.ok(r.startswith('BLE ping') and ('ble', 'android', 'headphones') in fired, 'do ble ping android')
t.ok('scan' not in nova.do('ble scan').lower() or 'devices' in nova.do('ble scan'), 'do ble scan')
t.ok(nova.do('bogus x').startswith('unknown'), 'unknown action')

sys.exit(t.done())
