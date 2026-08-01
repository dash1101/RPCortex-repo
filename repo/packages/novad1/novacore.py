# Desc: Nova D1 core — the shared foundation for cross-cutting helpers.
# File: /Packages/NovaD1/novacore.py
#
# Every Nova module needs the same couple of things — read/write a registry key. This
# module is the LEAF of the Nova dependency graph: it imports only `regedit` (lazily)
# plus the stdlib, so anything can depend on it without creating an import cycle. See
# ARCHITECTURE.md for the full layer map + dependency rule.
#
# Before this existed, ~11 modules each re-declared a near-identical `_reg`; they now
# do `from novacore import reg as _reg`. Behaviour is preserved exactly: a value that
# is missing OR empty ('') counts as absent, so the default is returned.
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

VERSION = '1.1'

# --- memory ----------------------------------------------------------------
# The device's hard failures are CONTIGUITY failures, not shortages: MicroPython's
# GC never compacts (py/gc.c is non-moving), so gc.mem_free() can report 90+ KB
# while the largest unbroken run is far smaller. A TLS handshake needs one
# unbroken ~16.7 KB block (mbedTLS MBEDTLS_SSL_IN_CONTENT_LEN is 16384 and the
# input buffer is a single m_tracked_calloc out of the GC heap), so "plenty free"
# and "cannot open HTTPS" are routinely both true at once.
#
# These helpers exist so every Nova screen handles that the same way: reclaim
# first, recognise BOTH shapes of out-of-memory, and say something a user can act
# on rather than printing a truncated errno.

ENOMEM = 12


def is_oom(exc):
    """True for either shape an out-of-memory takes on this firmware.

    MicroPython raises MemoryError for its own allocations, but an mbedTLS
    allocation failure comes back as OSError(ENOMEM): mbedTLS returns
    MBEDTLS_ERR_SSL_ALLOC_FAILED and extmod/modtls_mbedtls.c maps it to
    mp_raise_OSError(MP_ENOMEM). Code that checks only MemoryError misses every
    HTTPS failure."""
    if isinstance(exc, MemoryError):
        return True
    if isinstance(exc, OSError):
        try:
            return bool(exc.args) and exc.args[0] == ENOMEM
        except Exception:
            return False
    return False


def reclaim():
    """Free as much as possible and return the bytes now free.

    The shell's command cache is the single biggest reclaimable block on a
    working device, so drop that first via launchpad.free_heap(); fall back to a
    plain double collect when the shell isn't loaded. The second collect catches
    objects the first one made unreachable."""
    import gc
    try:
        import sys
        lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
        if lp is not None and hasattr(lp, 'free_heap'):
            return lp.free_heap()
    except Exception:
        pass
    try:
        gc.collect()
        gc.collect()
        return gc.mem_free()
    except Exception:
        return 0


def largest_block(cap=32768):
    """Size of the largest block that can actually be allocated right now, by
    probing. This is the number that matters; gc.mem_free() is not."""
    import gc
    lo, hi, best = 0, cap, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if mid <= 0:
            break
        try:
            b = bytearray(mid)
            del b
            best = mid
            lo = mid + 1024
        except MemoryError:
            hi = mid - 1024
    gc.collect()
    return best


def retry_oom(fn, tries=2):
    """Run fn(); on an out-of-memory, reclaim and try again.

    A first attempt often fails only because the shell's command cache is still
    resident. Retrying after a reclaim turns a dead end into a pause. Returns
    (ok, result_or_exception)."""
    last = None
    for attempt in range(max(1, tries)):
        try:
            return True, fn()
        except Exception as e:
            if not is_oom(e):
                raise
            last = e
            reclaim()
    return False, last


def oom_message():
    """A short line that fits a 128px panel and tells the user what to do."""
    return 'Low memory - reboot frees the most'


def reg(key, default=None):
    """Read a registry key; return `default` when it is missing or empty. regedit is
    imported lazily so a module that only occasionally touches config doesn't pay for
    it at import time (and so this file stays a dependency-free leaf)."""
    try:
        import regedit
        v = regedit.read(key)
        return v if v not in (None, '') else default
    except Exception:
        return default


def save_reg(key, value):
    """Write a registry key. Returns True on success, False if the store is
    unavailable — callers treat persistence as best-effort."""
    try:
        import regedit
        regedit.save(key, value)
        return True
    except Exception:
        return False
