# Messages: composing on the DEVICE. Writing a message used to mean opening the web
# panel on a phone — SELECT only ever broadcast a fixed 'ping'. Now SELECT opens the
# on-screen keyboard and HOLD SELECT is the ping, so the LoRa link is usable with
# nothing but the encoder.
import sys
import types
import _shims
_shims.install()
from _shims import T

import novagui_radios as R
from novaui import ev
import novagui_system

t = T('test_messages')

sent = []
msg = types.ModuleType('novamsg')
msg.inbox = lambda: []
msg.radio_ok = lambda: True
msg.send = lambda txt: sent.append(txt)
sys.modules['novamsg'] = msg

mesh = types.ModuleType('novamesh')
mesh.node_id = lambda: 7
sys.modules['novamesh'] = mesh

scr = R.MessagesScreen()

# SELECT opens the keyboard rather than firing a canned message
kb = scr.on_event(ev.SELECT)
t.ok(isinstance(kb, novagui_system.KeyboardScreen), 'SELECT opens the keyboard')
t.eq(sent, [], 'and nothing is transmitted just by opening it')
t.eq(kb.title, 'Message', 'the keyboard is labelled for what it composes')

# what gets typed is what gets sent
t.eq(kb._done('hello there'), 'back', 'accepting the text closes the keyboard')
t.eq(sent, ['hello there'], 'the typed text is what went out')

# an empty message is not transmitted
sent[:] = []
scr.on_event(ev.SELECT)._done('   ')
t.eq(sent, [], 'an empty message is not sent')

# HOLD SELECT keeps the quick ping
sent[:] = []
t.ok(scr.on_event(ev.SELECT_HOLD) is None, 'hold-SELECT stays on the screen')
t.eq(sent, ['ping 7'], 'hold-SELECT broadcasts the ping')

# a failing radio must not take the screen down with it
def _boom(txt):
    raise RuntimeError('no radio')


msg.send = _boom
t.ok(scr.on_event(ev.SELECT_HOLD) is None, 'a dead radio does not raise out of ping')
t.eq(scr._sent, 'ping failed', 'and the failure is reported on screen')
scr.on_event(ev.SELECT)._done('x')
t.eq(scr._sent, 'send failed', 'a failed send is reported too')

# The status is TRANSIENT. Left permanent it replaces the 'Sel=write hold=ping'
# hint forever, which is the stuck-activity-text bug all over again.
msg.send = lambda txt: sent.append(txt)
scr.on_event(ev.SELECT)._done('hi')
t.eq(scr._sent, 'sent', 'the send is confirmed on screen')
scr.tick(1000)
t.eq(scr._sent, 'sent', 'and stays up long enough to read')
t.ok(scr.tick(2000) is True, 'then expires, asking for a redraw')
t.ok(scr._sent is None, 'and the footer goes back to the hint')

t.ok(scr.on_event(ev.BACK) == ev.BACK, 'BACK still leaves the screen')

sys.exit(t.done())
