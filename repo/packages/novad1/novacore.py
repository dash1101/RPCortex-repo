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

VERSION = '1.0'


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
