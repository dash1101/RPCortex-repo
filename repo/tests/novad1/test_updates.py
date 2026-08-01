# UpdatesScreen: the check must be stepped, not one long block.
#
# Two HTTPS fetches back to back is a multi-second stall, and the GUI shares its
# event loop with the serial shell and the background services — doing both in one
# call froze all of them AND left the spinner motionless, which is the opposite of
# what a spinner is for. Each fetch is still atomic (net.wget is synchronous), so
# this bounds the stall to one request; it does not remove it.
import sys
import types
import _shims
_shims.install()
from _shims import T

t = T('test_updates')

fetched = []
OS_MANIFEST = '{"version": "v1.1.0", "build": "999", "notes": "newer"}'
IDX = '{"packages": [{"name": "NovaD1", "ver": "9.9.9"}]}'

net = types.ModuleType('net')
net.status = lambda: {'connected': True}


def _wget(url, dest=None, verbose=False, **kw):
    """The real call now streams to a file — the body is never held in RAM."""
    fetched.append(url)
    doc = IDX if 'index.json' in url else OS_MANIFEST
    if dest is None:
        return 200, doc
    with open(dest, 'w') as f:
        f.write(doc)
    return 200, len(doc)


net.wget = _wget
sys.modules['net'] = net

import novagui
import tempfile
import os as _os
novagui._FETCH_TMP = _os.path.join(tempfile.mkdtemp(), 'fetch.tmp')

scr = novagui.UpdatesScreen()

t.eq(scr.state, 'idle', 'the screen starts idle')
scr.tick(40)
t.eq(scr.state, 'checking', 'the first tick only switches to checking')
t.eq(fetched, [], 'nothing is fetched before the spinner has been painted')
scr.tick(40)
t.eq(fetched, [], 'the spinner frame still fetches nothing')

# one fetch per tick from here
scr.tick(40)
t.eq(len(fetched), 0, 'the first step only reports what it is about to do')
t.eq(scr._status, 'Checking OS...', 'and says so on screen')
scr.tick(40)
t.eq(len(fetched), 1, 'the OS manifest is fetched on its own step')
t.eq(scr._status, 'Checking app...', 'the status advances between fetches')
t.eq(scr.state, 'checking', 'the screen is still working')
scr.tick(40)
t.eq(len(fetched), 2, 'the package index is a separate step')
scr.tick(40)
t.eq(scr.state, 'done', 'then the check completes')

t.eq(scr.os_new[0], 'v1.1.0', 'a newer OS is detected')
t.eq(scr.pkg_new, '9.9.9', 'a newer package is detected')
t.eq(scr.err, '', 'and nothing errored')
labels = [r[1] for r in scr.rows]
t.ok(any('v1.1.0' in l for l in labels), 'the new OS version is offered')
t.ok(any('9.9.9' in l for l in labels), 'the new app version is offered')

# ------------------------------------------------------------- failure paths
def _boom(url, dest=None, verbose=False, **kw):
    raise OSError('connection reset')


net.wget = _boom
scr2 = novagui.UpdatesScreen()
for _ in range(8):
    scr2.tick(40)
t.eq(scr2.state, 'done', 'a failing fetch still finishes the check')
t.ok(scr2.err != '', 'and reports the failure')
t.ok(scr2.rows, 'the screen still has rows to show')

net.status = lambda: {'connected': False}
scr3 = novagui.UpdatesScreen()
for _ in range(8):
    scr3.tick(40)
t.eq(scr3.err, 'No WiFi', 'offline is reported as offline, not as a failed fetch')
t.eq(scr3.state, 'done', 'and the screen does not sit spinning forever')

# the spinner must be alive for the whole check, not just the first frame
net.status = lambda: {'connected': True}
net.wget = _wget
scr4 = novagui.UpdatesScreen()
spins = []
for _ in range(5):
    scr4.tick(40)
    spins.append(scr4._spin)
t.ok(scr4.animating() is False or len(set(spins)) > 1,
     'the spinner phase advances while the check runs')

# ------------------------------------------------ the body never lives in RAM
# net.wget(dest=...) streams to flash; the return-the-body form has to hold the
# whole document as one contiguous object, immediately after a TLS handshake has
# taken a 16.7 KB block out of a heap that never compacts.
import inspect
_src = inspect.getsource(novagui._fetch_json)
t.ok('dest=' in _src, 'the manifest fetch streams to a file, not into memory')

_dests = []


def _wget_check(url, dest=None, verbose=False, **kw):
    _dests.append(dest)
    doc = IDX if 'index.json' in url else OS_MANIFEST
    with open(dest, 'w') as f:
        f.write(doc)
    return 200, len(doc)


net.wget = _wget_check
net.status = lambda: {'connected': True}
scr5 = novagui.UpdatesScreen()
for _ in range(8):
    scr5.tick(40)
t.ok(_dests and all(d for d in _dests), 'every fetch supplied a destination file')
t.ok(not _os.path.exists(novagui._FETCH_TMP),
     'and the temp file is cleaned up afterwards')

# --------------------------------------------- out of memory is not a dead end
def _oom(url, dest=None, verbose=False, **kw):
    raise OSError(12)                      # ENOMEM, the shape mbedTLS raises


net.wget = _oom
scr6 = novagui.UpdatesScreen()
for _ in range(8):
    scr6.tick(40)
t.eq(scr6.state, 'done', 'an out-of-memory check still completes')
t.ok('memory' in scr6.err.lower(),
     'and is reported as a memory problem, not a generic failure (got {!r})'.format(
         scr6.err))
t.ok('reboot' in scr6.err.lower(), 'with something the user can actually do')

sys.exit(t.done())
