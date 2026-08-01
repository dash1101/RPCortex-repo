# novainput: button presses must never be lost.
#
# Reported: "sometimes I'll press a button and have to press it again for slightly
# longer." That is not a debounce problem, it is a SAMPLING problem. The UI loop
# naps 250-400 ms when idle and read the pins once per iteration, so a normal tap
# that began and ended inside one nap was never observed at all. Pressing longer
# only helped because it made the single sample land while the button was held.
#
# Buttons are captured by edge interrupt now, so the press is recorded the moment
# it happens no matter how long the loop sleeps. These tests drive the ISRs
# directly and check nothing is dropped.
import sys
import _shims
_shims.install()
from _shims import T

import novainput as ni

t = T('test_novainput')

CLOCK = {'t': 1000}


class _Pin:
    IN = 0
    OUT = 1
    PULL_UP = 2
    IRQ_RISING = 1
    IRQ_FALLING = 2

    def __init__(s, n, mode=0, pull=None):
        s.n = n
        s._v = 1
        s._handler = None

    def value(s, v=None):
        if v is None:
            return s._v
        s._v = v

    def irq(s, handler=None, trigger=0):
        s._handler = handler

    # test helpers
    def press(s):
        s._v = 0
        if s._handler:
            s._handler(s)

    def release(s):
        s._v = 1
        if s._handler:
            s._handler(s)


class _Machine:
    Pin = _Pin

    @staticmethod
    def disable_irq():
        return 0

    @staticmethod
    def enable_irq(_s):
        pass


sys.modules['machine'] = _Machine
import utime
utime.ticks_ms = lambda: CLOCK['t']
utime.ticks_diff = lambda a, b: a - b

PINS = {'enc_a': 1, 'enc_b': 2, 'enc_sw': 3, 'btn1': 4, 'btn2': 5}
src = ni.GpioSource(PINS)

t.ok(src._btn_irq, 'buttons attached an interrupt handler')

sel = src.btns[ni.SELECT]
back = src.btns[ni.BACK]
home = src.btns[ni.HOME]


def drain():
    out = []
    for _ in range(400):
        e = src.poll()
        if e is None:
            break
        out.append(e)
    return out


# ---------------------------------------------------- a tap inside one nap
# The whole bug: press and release both happen between two polls.
drain()
sel.press()
CLOCK['t'] += 40
sel.release()
CLOCK['t'] += 400                       # the loop was asleep for all of it
t.eq(drain(), [ni.SELECT],
     'a tap that begins and ends between polls is still delivered')

back.press()
CLOCK['t'] += 60
back.release()
CLOCK['t'] += 400
t.eq(drain(), [ni.BACK], 'the same for BACK')

home.press()
CLOCK['t'] += 60
home.release()
CLOCK['t'] += 400
t.eq(drain(), [ni.HOME], 'and for HOME')

# --------------------------------------------------------- taps QUEUE UP
# "I'd be fine if it queued the press" — several taps during one long nap must
# all arrive, in order, rather than collapsing into one.
for _ in range(4):
    sel.press()
    CLOCK['t'] += 60
    sel.release()
    CLOCK['t'] += 60
CLOCK['t'] += 400
t.eq(drain(), [ni.SELECT] * 4, 'four taps during one nap all queue up')

# mixed buttons keep their events
sel.press(); CLOCK['t'] += 60; sel.release(); CLOCK['t'] += 40
back.press(); CLOCK['t'] += 60; back.release(); CLOCK['t'] += 40
home.press(); CLOCK['t'] += 60; home.release()
CLOCK['t'] += 400
got = drain()
t.eq(sorted(got), sorted([ni.SELECT, ni.BACK, ni.HOME]),
     'presses of different buttons are all delivered')

# --------------------------------------------------------------- holds
drain()
sel.press()
CLOCK['t'] += ni.HOLD_MS + 50
sel.release()
t.eq(drain(), [ni.SELECT_HOLD], 'a long press is a hold, not a tap')

home.press()
CLOCK['t'] += ni.HOLD_MS + 50
home.release()
t.eq(drain(), [ni.HOME_HOLD], 'and HOME_HOLD for HOME')

# A hold must fire WHILE the button is down — HOME_HOLD opens the power screen,
# and waiting for the release would make it feel broken.
drain()
CLOCK['t'] += 60          # a real gap since the last release, not instant re-press
home.press()
CLOCK['t'] += ni.HOLD_MS + 10
t.eq(drain(), [ni.HOME_HOLD], 'the hold fires while the button is still held')
t.eq(drain(), [], 'and does not fire a second time')
home.release()
CLOCK['t'] += 10
t.eq(drain(), [], 'nor does releasing it then produce a tap as well')

# a short press after a hold is a tap again
sel.press(); CLOCK['t'] += 60; sel.release(); CLOCK['t'] += 60
t.eq(drain(), [ni.SELECT], 'a tap after a hold is still a tap')

# ------------------------------------------------------- rotation still works
drain()
src._count = 2
t.eq(src.poll(), ni.ROT_CW, 'encoder detents still come through')
t.eq(src.poll(), ni.ROT_CW, 'one per poll')
src._count = -1
t.eq(src.poll(), ni.ROT_CCW, 'both directions')

# rotation is delivered BEFORE queued presses, so a press acts on where the knob
# ended up rather than where it was
drain()
sel.press(); CLOCK['t'] += 60; sel.release()
src._count = 1
t.eq(src.poll(), ni.ROT_CW, 'a pending detent is delivered before a queued press')
t.eq(src.poll(), ni.SELECT, 'then the press')

# --------------------------------------------------- the counters cannot wrap
# The ISR increments a byte. It must saturate rather than wrap to zero, or a
# flurry of presses could silently reset the count.
drain()
for _ in range(300):
    back.press()
    CLOCK['t'] += 40
    back.release()
    CLOCK['t'] += 40
n = len(drain())
t.ok(n >= 32, 'a long burst queues rather than being lost ({} delivered)'.format(n))
t.ok(n <= 64, 'but the queue is bounded, so a stuck button cannot grow it forever')




# ------------------------------------------------- live hold duration
# held_ms lets the UI show a gesture IN PROGRESS. A hold that gives no feedback
# until it fires is indistinguishable from a button that did nothing.
drain()
t.eq(src.held_ms(ni.HOME), 0, 'nothing held reads as 0')
home.press()
CLOCK['t'] += 200
t.eq(src.held_ms(ni.HOME), 200, 'a held button reports how long it has been held')
CLOCK['t'] += 300
t.eq(src.held_ms(ni.HOME), 500, 'and keeps counting')
t.eq(src.held_ms(ni.SELECT), 0, 'a button that is up still reads 0')
home.release()
t.eq(src.held_ms(ni.HOME), 0, 'releasing resets it')
drain()
t.eq(src.held_ms('nonsense'), 0, 'an unknown event does not raise')

# --------------------------------------------------------- CONTACT BOUNCE
# One press must be ONE event. A mechanical switch chatters for a few ms on both
# edges; undebounced, every bounce pair counted as another tap, which is why a
# single press sometimes fired twice.
def bounce_press(pin, hold_ms=120, bounces=4):
    """A realistic press: chatter, settle, hold, chatter, release."""
    for _ in range(bounces):
        pin.press()
        CLOCK['t'] += 2
        pin.release()
        CLOCK['t'] += 2
    pin.press()                      # settles down
    CLOCK['t'] += hold_ms
    for _ in range(bounces):
        pin.release()
        CLOCK['t'] += 2
        pin.press()
        CLOCK['t'] += 2
    pin.release()
    CLOCK['t'] += 60


drain()
bounce_press(sel)
t.eq(drain(), [ni.SELECT], 'a bouncing SELECT press produces exactly one event')

bounce_press(back)
t.eq(drain(), [ni.BACK], 'a bouncing BACK press produces exactly one event')

bounce_press(home)
t.eq(drain(), [ni.HOME], 'a bouncing HOME press produces exactly one event')

# ...and a bouncing LONG press is still one hold, not a hold plus taps
bounce_press(sel, hold_ms=ni.HOLD_MS + 100)
t.eq(drain(), [ni.SELECT_HOLD], 'a bouncing long press is one hold')

# two genuinely separate presses are still two events
drain()
sel.press(); CLOCK['t'] += 80; sel.release(); CLOCK['t'] += 80
sel.press(); CLOCK['t'] += 80; sel.release(); CLOCK['t'] += 80
t.eq(drain(), [ni.SELECT, ni.SELECT],
     'two real presses are still two events — the debounce does not merge them')

sys.exit(t.done())
