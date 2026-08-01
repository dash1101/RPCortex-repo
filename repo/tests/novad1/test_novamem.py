# novacore memory helpers + the screens that use them.
#
# The device's hard stops are CONTIGUITY failures, not shortages. MicroPython's GC
# never compacts (py/gc.c is non-moving), so gc.mem_free() can report 90+ KB while
# the largest unbroken run is far smaller -- and a TLS handshake needs one unbroken
# ~16.7 KB block, because mbedTLS is built with MBEDTLS_SSL_IN_CONTENT_LEN 16384 and
# takes the input buffer as a single m_tracked_calloc out of that same heap.
#
# Two user-visible consequences, both covered here:
#   - an out-of-memory arrives as OSError(ENOMEM) from mbedTLS, NOT MemoryError, so
#     code that checks only MemoryError misses every HTTPS failure
#   - a first failure is often only the shell's command cache being resident, so a
#     reclaim-and-retry turns a dead end into a pause
import sys
import types
import _shims
_shims.install()
from _shims import T

import novacore

t = T('test_novamem')

# ------------------------------------------------------- both shapes of OOM
t.ok(novacore.is_oom(MemoryError()), "MicroPython's own MemoryError is out-of-memory")
t.ok(novacore.is_oom(OSError(12)),
     'OSError(ENOMEM) -- what an mbedTLS alloc failure becomes -- is too')
t.ok(not novacore.is_oom(OSError(104)), 'a connection reset is not out-of-memory')
t.ok(not novacore.is_oom(OSError()), 'an argument-less OSError does not crash the check')
t.ok(not novacore.is_oom(ValueError('invalid cert')), 'nor is a bad certificate')
t.ok(not novacore.is_oom(RuntimeError('nope')), 'nor an unrelated error')

# ------------------------------------------------------------- reclaim + retry
calls = {'n': 0, 'reclaims': 0}
_real_reclaim = novacore.reclaim
novacore.reclaim = lambda: calls.__setitem__('reclaims', calls['reclaims'] + 1) or 1


def _fails_once():
    calls['n'] += 1
    if calls['n'] == 1:
        raise OSError(12)
    return 'scanned'


ok, res = novacore.retry_oom(_fails_once)
t.ok(ok, 'a transient out-of-memory succeeds on the retry')
t.eq(res, 'scanned', 'and returns the real result')
t.eq(calls['reclaims'], 1, 'exactly one reclaim happened in between')

calls['n'] = 0
calls['reclaims'] = 0


def _always_fails():
    calls['n'] += 1
    raise MemoryError()


ok, res = novacore.retry_oom(_always_fails)
t.ok(not ok, 'a persistent out-of-memory reports failure rather than raising')
t.ok(isinstance(res, MemoryError), 'and hands back the exception for the caller')
t.eq(calls['n'], 2, 'after the configured number of attempts')

# a NON-memory error must propagate — retrying a bad cert or a reset is pointless
calls['n'] = 0


def _other():
    calls['n'] += 1
    raise ValueError('bad cert')


try:
    novacore.retry_oom(_other)
    t.ok(False, 'a non-memory error should propagate')
except ValueError:
    t.ok(True, 'a non-memory error propagates instead of being retried')
t.eq(calls['n'], 1, 'and is not retried')

novacore.reclaim = _real_reclaim

# ------------------------------------------------------------ the user message
msg = novacore.oom_message()
t.ok(len(msg) <= 34, 'the message fits a 128px panel ({} chars)'.format(len(msg)))
t.ok('memory' in msg.lower(), 'it names the actual problem')
t.ok('reboot' in msg.lower(), 'and says what actually helps')

# ------------------------------------------------------ largest_block probes
n = novacore.largest_block(cap=8192)
t.ok(n > 0, 'largest_block finds a real allocatable size')
t.ok(n <= 8192, 'and respects its cap')

# ------------------------------------------- the WiFi scan recovers, not dies
net = types.ModuleType('net')
net.status = lambda: {'connected': False}
net._read_networks = lambda: []
net.add_network = lambda s, p: True
net.connect = lambda s, p=None: False
net.connect_saved = lambda s=None: False
sys.modules['net'] = net

import network
scan_calls = {'n': 0}


class _WLAN:
    def __init__(s, *a):
        pass

    def active(s, v=None):
        return True

    def isconnected(s):
        return False

    def scan(s):
        scan_calls['n'] += 1
        if scan_calls['n'] == 1:
            raise MemoryError()          # the burst fails the first time
        return [(b'dash_', b'\x00' * 6, 6, -50, 3, False)]


network.WLAN = _WLAN

import novagui_system
scr = novagui_system.WiFiScreen()
scr._do_scan()
t.eq(scan_calls['n'], 2, 'a failed scan is retried after reclaiming')
t.ok([n[0] for n in scr.nets] == ['dash_'],
     'and the retry produces the networks (got {})'.format(scr.nets))

# when it never recovers, the message must be useful. It used to read
# 'scan err: memory allo' -- a truncated errno with no way forward.
scan_calls['n'] = 0


class _DeadWLAN(_WLAN):
    def scan(s):
        scan_calls['n'] += 1
        raise MemoryError()


network.WLAN = _DeadWLAN
scr2 = novagui_system.WiFiScreen()
scr2._do_scan()
t.eq(scr2.nets, [], 'a scan that cannot recover leaves no stale networks')
t.ok('memory' in scr2.msg.lower(),
     'and says it is a memory problem (got {!r})'.format(scr2.msg))
t.ok('err:' not in scr2.msg, 'not a truncated errno')
t.ok(len(scr2.msg) <= 34, 'and it fits the panel')

sys.exit(t.done())
