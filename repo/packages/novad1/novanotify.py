# Desc: Nova D1 notifications — a tiny shared notification queue + unread count.
# File: /Packages/NovaD1/novanotify.py
#
# Foundation for the top-bar bell + a Notifications app + background alerts. Any
# app, service, the shell (`novad1 notify`), or the web panel (/notify) can push
# one. Gated by Apps.NovaD1_Notify (default on). Pure state (no hardware), so the
# logic is CPython-testable. MicroPython-safe: no f-strings.

_NOTES = []          # list of (ts_str, text), oldest first
_MAX = 20
_unread = 0


def _reg(key, default):
    try:
        import regedit
        v = regedit.read(key)
        return v if v not in (None, '') else default
    except Exception:
        return default


def enabled():
    return str(_reg('Apps.NovaD1_Notify', 'on')).lower() not in ('off', 'false', '0')


def _ts():
    try:
        import utime
        t = utime.localtime()
        return '{:02d}:{:02d}'.format(t[3], t[4])
    except Exception:
        return '--:--'


def notify(text):
    """Push a notification (no-op if notifications are disabled)."""
    if not enabled():
        return False
    global _unread
    _NOTES.append((_ts(), str(text)[:60]))
    if len(_NOTES) > _MAX:
        _NOTES.pop(0)
    _unread += 1
    return True


def count():
    return _unread


def items():
    return list(_NOTES)


def mark_read():
    global _unread
    _unread = 0


def clear():
    global _unread
    _NOTES[:] = []
    _unread = 0
