# Desc: Nova D1 timekeeping — NTP-on-connect + optional DS3231 battery-backed RTC.
# File: /Packages/NovaD1/novartc.py
#
# machine.RTC() already keeps time while the board is powered (the LiPo covers it;
# it only resets on a full power loss) — so we DON'T build a soft clock. We just:
#   boot_sync()   : if a DS3231 (0x68) is present, load it into the system RTC so
#                   time is right even with no WiFi.
#   online_sync() : once online, NTP-sync the system RTC, then persist to the
#                   DS3231 if present (so it survives a full power loss).
# MicroPython-safe: no f-strings, positional split, .format() only.

_DS = 0x68


def _reg(key, default):
    try:
        import regedit
        v = regedit.read(key)
        return v if v not in (None, '') else default
    except Exception:
        return default


def _i2c():
    import machine
    return machine.I2C(0, scl=machine.Pin(int(_reg('Apps.NovaD1_SCL', 9))),
                       sda=machine.Pin(int(_reg('Apps.NovaD1_SDA', 8))), freq=400000)


def _b2d(b):
    return (b >> 4) * 10 + (b & 0x0F)


def _d2b(v):
    return ((v // 10) << 4) | (v % 10)


def read_to_rtc():
    """DS3231 -> system RTC. True if a DS3231 was present and read."""
    import machine
    i2c = _i2c()
    if _DS not in i2c.scan():
        return False
    d = i2c.readfrom_mem(_DS, 0x00, 7)
    sec = _b2d(d[0] & 0x7F)
    mn = _b2d(d[1] & 0x7F)
    hr = _b2d(d[2] & 0x3F)
    day = _b2d(d[4] & 0x3F)
    mon = _b2d(d[5] & 0x1F)
    yr = 2000 + _b2d(d[6])
    machine.RTC().datetime((yr, mon, day, 0, hr, mn, sec, 0))
    return True


def write_from_rtc():
    """System RTC -> DS3231. True if a DS3231 was present and written."""
    import machine
    i2c = _i2c()
    if _DS not in i2c.scan():
        return False
    t = machine.RTC().datetime()           # (yr, mon, day, wd, hr, mn, sec, sub)
    buf = bytes([_d2b(t[6]), _d2b(t[5]), _d2b(t[4]), 1,
                 _d2b(t[2]), _d2b(t[1]), _d2b(t[0] % 100)])
    i2c.writeto_mem(_DS, 0x00, buf)
    return True


def boot_sync():
    try:
        return read_to_rtc()
    except Exception:
        return False


def online_sync():
    """NTP-sync the clock, then persist to the DS3231 if present. Best-effort."""
    import sys
    ok = False
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
    if lp is not None and hasattr(lp, '_run_line'):
        try:
            lp._run_line('ntp sync -s')
            ok = True
        except Exception:
            pass
    try:
        write_from_rtc()
    except Exception:
        pass
    return ok
