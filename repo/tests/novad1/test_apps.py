# The kind:py store apps (baseconv/counter/timer/flashlight/totp): each loads to a
# Screen, and the pure logic is unit-tested — TOTP against CPython hashlib + the
# RFC 6238 test vectors, so the on-device pure-Python SHA1/HMAC is provably correct.
import sys
import os
import hashlib
import _shims
_shims.install()
from _shims import T
import novaui
import novainput as ev
import nova

t = T('test_apps')
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'novad1-apps')


def load_ns(app_dir, entry):
    """exec an app's entry .py with the same names the loader injects -> its namespace."""
    src = open(os.path.join(STORE, app_dir, entry)).read()
    ns = {'ui': novaui, 'ev': novaui.ev, 'nova': nova}
    exec(src, ns)
    return ns


class _C:                                   # a throwaway canvas that records nothing
    w = 128
    h = 64
    def text(self, *a, **k): pass
    def rect(self, *a, **k): pass
    def fill_rect(self, *a, **k): pass
    def line(self, *a, **k): pass
    def hline(self, *a, **k): pass
    def pixel(self, *a, **k): pass
    def char(self, *a, **k): pass


# --- every new app loads to a working Screen + renders without error ---------
for d, entry in (('baseconv', 'baseconv.py'), ('counter', 'counter.py'),
                 ('timer', 'timer.py'), ('flashlight', 'flashlight.py'),
                 ('totp', 'totp.py')):
    ns = load_ns(d, entry)
    t.ok(callable(ns.get('app')), '{}: defines app()'.format(d))
    scr = ns['app']()
    t.ok(hasattr(scr, 'draw') and hasattr(scr, 'on_event'), '{}: app() -> Screen'.format(d))
    scr.draw(_C())                          # renders clean
    t.eq(scr.on_event(ev.BACK), ev.BACK, '{}: BACK exits'.format(d))

# --- Base Convert: the DEC/HEX/BIN core ---
bc = load_ns('baseconv', 'baseconv.py')
d, h, b = bc['_bases'](255)
t.eq(h, 'HEX  00FF', 'baseconv hex of 255')
t.eq(b, 'BIN  0000000011111111', 'baseconv binary of 255')
t.eq(bc['_bases'](0x10000 + 5)[0], 'DEC  5', 'baseconv wraps to 16 bits')
sc = bc['app']()
sc.on_event(ev.SELECT)                      # step -> 16
sc.on_event(ev.ROT_CW)
t.eq(sc.n, 16, 'baseconv step applies to the value')

# --- Timer: MM:SS formatting + countdown ---
tm = load_ns('timer', 'timer.py')
t.eq(tm['_fmt'](0), '00:00', 'timer fmt zero')
t.eq(tm['_fmt'](75), '01:15', 'timer fmt 75s')
ts = tm['app']()
ts.total = 2
ts.on_event(ev.SELECT)                      # start
t.ok(ts.run and ts.left == 2, 'timer starts running')
ts.tick(1000); ts.tick(1000)                # two seconds -> hits zero
t.ok(ts.done and not ts.run, 'timer finishes at zero')

# --- TOTP: prove the pure crypto chain ---
tp = load_ns('totp', 'totp.py')
_sha1 = tp['_sha1']
for m in (b'', b'abc', b'The quick brown fox jumps over the lazy dog', b'x' * 200):
    t.eq(_sha1(m), hashlib.sha1(m).digest(), 'sha1 matches hashlib ({} bytes)'.format(len(m)))

# HMAC-SHA1 matches Python's hmac
import hmac as _hmac
t.eq(tp['_hmac_sha1'](b'key', b'msg'),
     _hmac.new(b'key', b'msg', hashlib.sha1).digest(), 'hmac-sha1 matches hmac module')

# base32 of the RFC 6238 test secret decodes to the ASCII seed
SEC = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
t.eq(tp['_b32decode'](SEC), b'12345678901234567890', 'base32 decode of the RFC secret')

# RFC 6238 SHA1 vectors (8-digit, and the 6-digit low bits our app shows)
totp = tp['totp']
t.eq(totp(SEC, 59, digits=8), '94287082', 'RFC6238 T=59')
t.eq(totp(SEC, 1111111109, digits=8), '07081804', 'RFC6238 T=1111111109')
t.eq(totp(SEC, 1234567890, digits=8), '89005924', 'RFC6238 T=1234567890')
t.eq(totp(SEC, 20000000000, digits=8), '65353130', 'RFC6238 T=20000000000')
t.eq(totp(SEC, 59), '287082', 'RFC6238 T=59 (6-digit)')

# lower-case + spaced secret still decodes (real secrets are shown grouped)
t.eq(totp('gezd gnbv gy3t qojq gezd gnbv gy3t qojq', 59, digits=8), '94287082',
     'secret is space/case tolerant')

# the app lists accounts from the totp store and computes a code
import novastore
novastore.list_codes = lambda cat: ['github.txt'] if cat == 'totp' else []
novastore.read_code = lambda cat, n: ('GitHub: ' + SEC) if cat == 'totp' else None
scr = tp['app']()
t.ok(scr.accts and scr.code != '------', 'totp app loads an account + shows a code')

sys.exit(t.done())
