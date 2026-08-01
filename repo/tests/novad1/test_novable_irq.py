# novable.scan_steps: the BLE scan callback runs in an INTERRUPT, once per
# advertisement, many times a second. Two things have to hold there: it must not
# raise, and it must not allocate more than it has to — undebounced allocation in
# that path is what fragmented the heap into 1 KB scraps.
import sys
import types
import _shims
_shims.install()
from _shims import T

t = T('test_novable_irq')

import novable

# `addr` and `adv` arrive as memoryviews from the BLE stack. A memoryview is
# UNHASHABLE, so using it as a dict key raised TypeError inside the interrupt for
# every advertisement seen.
captured = {}


class _BLE:
    def __init__(s):
        s._h = None

    def active(s, v=None):
        return True

    def irq(s, h):
        s._h = h
        captured['h'] = h

    def gap_scan(s, *a):
        return None


novable._radio = lambda: _BLE()

gen = novable.scan_steps(10)
next(gen)                                     # starts the scan, installs the irq
h = captured.get('h')
t.ok(h is not None, 'the scan installs an interrupt handler')

mac = memoryview(b'\xaa\xbb\xcc\xdd\xee\xff')
adv = memoryview(bytes([2, 0x01, 0x06]))
try:
    h(novable._IRQ_SCAN_RESULT, (0, mac, 0, -55, adv))
    t.ok(True, 'a memoryview address does not raise in the interrupt')
except TypeError as e:
    t.ok(False, 'memoryview address raised: {}'.format(e))

# DEVICE-UNCONFIRMED by construction: CPython hashes a read-only memoryview, so
# `found.get(addr)` works here and FAILED on the device with
# "TypeError: unsupported type for __hash__: 'memoryview'". A host test can
# therefore never catch this one by running it — only by reading the source and
# insisting the conversion is explicit.
import inspect
src = inspect.getsource(novable.scan_steps)
body = src[src.index('def _irq'):]
body = body[:body.index('\n    try:')] if '\n    try:' in body else body
code = '\n'.join(l.split('#')[0] for l in body.split('\n'))
t.ok('found.get(addr)' not in code,
     'the interrupt never looks up by the raw memoryview')
t.ok('key = bytes(addr)' in code,
     'it converts the address once, explicitly, before using it as a key')
t.ok(code.count('bytes(addr)') == 1,
     'and converts it ONCE, not per use — this runs per advertisement')

# a second, weaker sighting of the same device must not replace the stronger one
try:
    h(novable._IRQ_SCAN_RESULT, (0, mac, 0, -80, adv))
    t.ok(True, 'a repeat sighting does not raise either')
except Exception as e:
    t.ok(False, 'repeat sighting raised: {}'.format(e))

# the result set is bounded, so a crowded room cannot fill the heap
for i in range(novable.MAX_RESULTS + 30):
    m = memoryview(bytes([i // 256, i % 256, 0, 0, 0, 1]))
    try:
        h(novable._IRQ_SCAN_RESULT, (0, m, 0, -60, adv))
    except Exception as e:
        t.ok(False, 'bounded fill raised: {}'.format(e))
        break

res = None
for res in gen:
    pass
t.ok(isinstance(res, list), 'the scan yields a list of results')
t.ok(len(res) <= novable.MAX_RESULTS,
     'and never more than MAX_RESULTS ({} of {})'.format(len(res), novable.MAX_RESULTS))
for d in res:
    t.ok(isinstance(d['mac'], str) and ':' in d['mac'],
         'each result carries a formatted MAC')
    break

sys.exit(t.done())
