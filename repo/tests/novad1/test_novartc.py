# novartc: the NTP sync must never block the event loop.
#
# The reported bug was "ntp sync freezes the OS". The cause was structural, not a
# slow network: novawifi.manager() is a coroutine, and it called the SYNCHRONOUS
# novartc.online_sync() without an await. That call does a DNS lookup and then a
# recv() with a multi-second timeout, so the whole loop — including the GUI, which
# runs on it — stopped dead on first WiFi connect. These assertions pin the shape
# of the fix: the work is a generator that yields at every wait.
import sys
import types
import _shims
_shims.install()
from _shims import T

import novartc

t = T('test_novartc')

# --- a fake UDP socket that answers only after several polls -----------------
import struct as _struct

_state = {'polls': 0, 'answer_after': 3, 'resolves': 0, 'sent': 0, 'closed': 0,
          'blocking': None}


def _ntp_reply(secs_since_1900):
    b = bytearray(48)
    b[40:44] = _struct.pack('!I', secs_since_1900)
    return bytes(b)


class _Sock:
    def __init__(s, *a):
        pass

    def setblocking(s, v):
        _state['blocking'] = v

    def sendto(s, pkt, addr):
        _state['sent'] += 1

    def recv(s, n):
        _state['polls'] += 1
        if _state['polls'] < _state['answer_after']:
            raise OSError(11)                   # EAGAIN — nothing yet
        return _state['reply']

    def close(s):
        _state['closed'] += 1


sock = types.ModuleType('socket')
sock.AF_INET = 2
sock.SOCK_DGRAM = 2
sock.socket = _Sock


def _gai(host, port):
    _state['resolves'] += 1
    return [(2, 2, 0, '', ('1.2.3.4', 123))]


sock.getaddrinfo = _gai
sys.modules['socket'] = sock

# a time the device can actually be set to (2026-01-01), in NTP-epoch seconds
_state['reply'] = _ntp_reply(3975004800)

# ------------------------------------------------------------------ it yields
novartc._ntp_addr = None
novartc.write_from_rtc = lambda: False          # no DS3231 in this fixture
steps = list(novartc.sync_steps())
t.ok(len(steps) >= 4, 'the sync is broken into steps, not one blocking call')
t.eq(steps[0], 'resolving', 'the DNS lookup is its own step')
t.ok('requesting' in steps, 'the request is its own step')
t.ok('waiting' in steps, 'each poll for the reply is a separate yield')
t.ok(steps.count('waiting') >= 2,
     'a reply that has not arrived yields again rather than blocking')
t.eq(steps[-1], True, 'the last value reports success')
t.ok(_state['closed'] >= 1, 'the socket is closed even on the success path')
t.ok(_state['blocking'] is False, 'the socket is put in non-blocking mode')

# ------------------------------------------------------- the address is cached
# This port has no resolver cache, so getaddrinfo is a fresh blocking round-trip
# every time — usually the longer of the two stalls.
_state['resolves'] = 0
_state['polls'] = 0
out = list(novartc.sync_steps())
t.eq(_state['resolves'], 0, 'a second sync reuses the cached address')
t.ok('resolving' not in out, 'and skips the resolve step entirely')

# ------------------------------------------------- a bad reply re-resolves once
_state['reply'] = b'\x00' * 8                   # short/garbage reply
_state['polls'] = 0
_state['answer_after'] = 1
bad = list(novartc.sync_steps())
t.eq(bad[-1], False, 'a short reply reports failure')
t.ok(novartc._ntp_addr is None,
     'and the cached address is dropped so the next try re-resolves')

# ----------------------------------------------------- a timeout is not a hang
_state['reply'] = b''
_state['polls'] = 0
_state['answer_after'] = 10 ** 9                # never answers
novartc._ntp_addr = ('1.2.3.4', 123)
slow = list(novartc.sync_steps(timeout_ms=30))
t.eq(slow[-1], False, 'a server that never answers gives up')
t.ok(_state['closed'] >= 3, 'and still closes its socket')

# ------------------------------------------------ the blocking wrapper survives
novartc._ntp_addr = ('1.2.3.4', 123)
_state['reply'] = _ntp_reply(3975004800)
_state['polls'] = 0
_state['answer_after'] = 2
t.ok(novartc.online_sync() is True,
     'online_sync still works for callers that are NOT on the event loop')

# --------------------------------------- the manager awaits instead of blocking
import novawifi
src = novawifi.manager.__doc__ or ''
t.ok(hasattr(novawifi, '_sync_clock'), 'the manager has an awaitable clock sync')
import inspect
t.ok(inspect.iscoroutinefunction(novawifi._sync_clock),
     'and it is a coroutine, so the loop is handed back between steps')
mgr = inspect.getsource(novawifi.manager)
t.ok('online_sync()' not in mgr,
     'the manager no longer calls the blocking sync from inside a coroutine')
t.ok('await _sync_clock()' in mgr, 'it awaits the stepped one instead')

sys.exit(t.done())
