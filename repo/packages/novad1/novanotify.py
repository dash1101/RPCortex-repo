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


from novacore import reg as _reg


def enabled():
    return str(_reg('Apps.NovaD1_Notify', 'on')).lower() not in ('off', 'false', '0')


def _ts():
    # Apply System.TZ_Offset (whole hours) like the status-bar clock, so a
    # notification's time matches the wall clock instead of UTC/RTC.
    try:
        import utime
        off = int(_reg('System.TZ_Offset', 0))
        t = utime.localtime(utime.time() + off * 3600)
        return '{:02d}:{:02d}'.format(t[3], t[4])
    except Exception:
        return '--:--'


def _haptic_alert():
    """A brief vibe pulse + a few short fast buzzer chirps on a new notification.
    Fully guarded: gated by Apps.NovaD1_Notify_Haptic (default on), and every
    hardware call is try/excepted — so it silently does nothing when the buzzer/
    vibe aren't wired, when off-device, or when disabled. Never raises into
    notify()."""
    if str(_reg('Apps.NovaD1_Notify_Haptic', 'on')).lower() in ('off', 'false', '0'):
        return
    try:
        import machine
        import utime
        import novaboard
    except Exception:
        return
    vp = novaboard.pin('vibe')
    if vp is not None:
        try:
            p = machine.Pin(vp, machine.Pin.OUT)
            p.value(1)
            utime.sleep_ms(120)
            p.value(0)
        except Exception:
            pass
    bz = novaboard.pin('buzzer')
    if bz is not None:
        try:
            pwm = machine.PWM(machine.Pin(bz))
            for f in (2400, 2800, 3200):        # short, fast, rising chirps
                pwm.freq(f)
                pwm.duty_u16(16000)
                utime.sleep_ms(45)
                pwm.duty_u16(0)
                utime.sleep_ms(28)
            pwm.deinit()
        except Exception:
            pass


def notify(text):
    """Push a notification (no-op if notifications are disabled). Fires a short
    vibe + buzzer alert on the way in (guarded; no-op if unwired)."""
    if not enabled():
        return False
    global _unread
    _NOTES.append((_ts(), str(text)[:60]))
    if len(_NOTES) > _MAX:
        _NOTES.pop(0)
    _unread += 1
    _haptic_alert()
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
