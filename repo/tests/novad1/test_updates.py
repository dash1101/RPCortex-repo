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

# Point the temp file at a directory that does NOT exist yet. /Vela/nova is only
# created once something touches the code store, so a device where Settings ->
# Updates is opened before Scripts hits exactly this. Pre-creating the parent
# here would test something the device never does.
_TMPROOT = tempfile.mkdtemp()
novagui._FETCH_TMP = _os.path.join(_TMPROOT, 'nova', 'fetch.tmp')
assert not _os.path.exists(_os.path.dirname(novagui._FETCH_TMP))

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
t.eq(scr._status, 'Freeing memory...',
     'the heap is reclaimed BEFORE the first handshake, not after it fails')
scr.tick(40)
t.eq(scr._status, 'Checking OS...', 'then the OS check is announced')
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
for _ in range(10):
    scr2.tick(40)
t.eq(scr2.state, 'done', 'a failing fetch still finishes the check')
t.ok(scr2.err != '', 'and reports the failure')
t.ok(scr2.rows, 'the screen still has rows to show')

net.status = lambda: {'connected': False}
scr3 = novagui.UpdatesScreen()
for _ in range(10):
    scr3.tick(10)
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
for _ in range(10):
    scr5.tick(40)
t.ok(_dests and all(d for d in _dests), 'every fetch supplied a destination file')
t.ok(_os.path.isdir(_os.path.dirname(novagui._FETCH_TMP)),
     'the temp directory is created when it does not already exist')
t.ok(not _os.path.exists(novagui._FETCH_TMP),
     'and the temp file itself is cleaned up afterwards')

# --------------------------------------------- out of memory is not a dead end
def _oom(url, dest=None, verbose=False, **kw):
    raise OSError(12)                      # ENOMEM, the shape mbedTLS raises


net.wget = _oom
scr6 = novagui.UpdatesScreen()
for _ in range(10):
    scr6.tick(40)
t.eq(scr6.state, 'done', 'an out-of-memory check still completes')
t.ok('ram' in scr6.err.lower() or 'memory' in scr6.err.lower(),
     'and is reported as a memory problem, not a generic failure (got {!r})'.format(
         scr6.err))
t.ok('reboot' in scr6.err.lower(), 'with something the user can actually do')
t.ok(len(scr6.err) <= 22, 'and it fits the panel ({} chars)'.format(len(scr6.err)))

# The reason has to distinguish the two things that actually go wrong, because
# they need completely different responses. 'OS check failed' told you nothing.
t.eq(novagui._fail_reason(OSError('[Errno 110] ETIMEDOUT'), 'OS'), 'Timed out',
     'a timeout is reported as a timeout')
t.eq(novagui._fail_reason(OSError('[Errno 104] ECONNRESET'), 'OS'),
     'Connection reset', 'a reset is reported as a reset')
t.eq(novagui._fail_reason(OSError(-202), 'OS'), 'DNS lookup failed',
     'a DNS failure is named')

# ------------------------------------------- "up to date" must mean CHECKED
# Reported: on 0.71.0 with 0.72.0 available, the screen said everything was up to
# date. Both the "current" and the "could not check" cases rendered as 'up to
# date', and the reason was appended as the LAST row -- below the six that fit --
# so a failed check was indistinguishable from a successful one.
net.status = lambda: {'connected': True}


def _boom2(url, dest=None, verbose=False, **kw):
    raise OSError('connection reset')


net.wget = _boom2
scr7 = novagui.UpdatesScreen()
for _ in range(10):
    scr7.tick(40)
labels = [r[1] for r in scr7.rows]
t.ok(not any('up to date' in l for l in labels),
     'a failed check never claims up to date (got {})'.format(labels))
t.ok(any('not checked' in l for l in labels), 'it says it could not check')
t.ok('!' in labels[0], 'and the reason is the FIRST row, where it is visible')

# versions are compared numerically, not as strings
t.ok(novagui._newer('0.72.0', '0.71.0'), '0.72.0 is newer than 0.71.0')
t.ok(not novagui._newer('0.71.0', '0.71.0'), 'the same version is not an update')
t.ok(not novagui._newer('0.70.0', '0.71.0'),
     'an OLDER index is not offered as an update')
t.ok(not novagui._newer('0.9.0', '0.72.0'),
     '0.9.0 is not newer than 0.72.0 -- string compare gets this backwards')
t.ok(novagui._newer('v1.0.0', 'v0.9.1'), 'a leading v is handled')
t.ok(not novagui._newer('?', '0.71.0'), 'an unknown available version is not an update')

# the index fetch carries a cache-buster: raw.githubusercontent serves /main/ from
# a CDN that can hold a stale copy for minutes after a push, which looks exactly
# like "no update available"
import inspect as _i
t.ok('_cache_bust()' in _i.getsource(novagui.UpdatesScreen._check_steps),
     'the index fetch is cache-busted')

sys.exit(t.done())
