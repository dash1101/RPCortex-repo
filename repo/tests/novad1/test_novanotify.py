# novanotify: the shared notification queue + unread count (pure state).
import sys
import _shims
_shims.install()
from _shims import T
import novanotify as N

t = T('test_novanotify')

_shims.set_reg({})                          # Notify defaults on
N.clear()
t.ok(N.enabled(), 'notifications default on')
t.ok(N.notify('hello'), 'notify returns True when enabled')
t.eq(N.count(), 1, 'unread increments')
t.eq(len(N.items()), 1, 'item queued')
t.eq(N.items()[0][1], 'hello', 'item text stored')

# text is capped at 60 chars
N.notify('x' * 200)
t.eq(len(N.items()[-1][1]), 60, 'text truncated to 60')

# mark_read zeroes the count but keeps the history
N.mark_read()
t.eq(N.count(), 0, 'mark_read clears unread')
t.ok(len(N.items()) >= 1, 'mark_read keeps the items')

# the queue is bounded at _MAX
N.clear()
for i in range(30):
    N.notify('n{}'.format(i))
t.eq(len(N.items()), N._MAX, 'queue bounded at _MAX')
t.eq(N.items()[-1][1], 'n29', 'newest kept')
t.eq(N.items()[0][1], 'n{}'.format(30 - N._MAX), 'oldest dropped')

# disabled -> notify is a no-op
_shims.set_reg({'Apps.NovaD1_Notify': 'off'})
N.clear()
t.ok(not N.enabled(), 'off disables')
t.ok(not N.notify('nope'), 'notify returns False when disabled')
t.eq(N.count(), 0, 'nothing queued when disabled')

# clear resets everything
_shims.set_reg({})
N.notify('a')
N.clear()
t.eq(N.count(), 0, 'clear zeroes count')
t.eq(len(N.items()), 0, 'clear empties queue')

# --------------------------------------------------- the onboard LED alert
# The board has no addressable NeoPixel any more, so the status LED signals
# notifications instead. It must be gated, and it must NEVER raise into notify()
# — a board with no LED at all still has to be able to post a notification.
_shims.set_reg({})
t.ok(N._led_alert() is None, 'the LED alert runs clean with nothing wired')
_shims.set_reg({'Apps.NovaD1_Notify_LED': 'off'})
t.ok(N._led_alert() is None, 'and is a no-op when switched off')

_boom = []
import machine as _m
_realpin = _m.Pin


class _DeadPin:
    def __init__(s, *a, **k):
        _boom.append(1)
        raise RuntimeError('no such pin')


_m.Pin = _DeadPin
_shims.set_reg({})
try:
    t.ok(N.notify('still works') is True,
         'a notification posts even when the LED pin blows up')
finally:
    _m.Pin = _realpin

sys.exit(t.done())
