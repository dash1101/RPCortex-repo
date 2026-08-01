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


from novacore import reg as _reg


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


_NTP_HOSTS = ('pool.ntp.org', 'time.google.com')
_ntp_addr = None            # cached resolved address — see sync_steps()


def _ntp_epoch_delta():
    """Seconds between the NTP epoch (1900) and this port's time epoch. MicroPython
    counts from 2000, CPython from 1970, so the constant can't be hard-coded."""
    import time
    try:
        return 3155673600 if time.gmtime(0)[0] == 2000 else 2208988800
    except Exception:
        return 3155673600


def sync_steps(timeout_ms=4000):
    """NTP-sync the clock as a GENERATOR, yielding a status between every step.

    This exists because the blocking version froze the whole device. `ntp sync`
    does a DNS lookup and then a recv() with a 5s timeout; called from the async
    WiFi manager it stalled the event loop — and the GUI runs on that loop, so the
    UI locked up on first connect. Here every wait is a yield, so the caller (the
    UI loop or an asyncio task) keeps running.

    The resolved address is CACHED in a module global: this port has no resolver
    cache, so getaddrinfo is a fresh blocking round-trip every time and is usually
    the LONGER of the two stalls. A stale entry just fails and gets re-resolved.

    Yields a short status string; the final yield is True on success, False on
    failure, so a driver can read the outcome off the last value.

    DEVICE-UNCONFIRMED: non-blocking UDP recv semantics differ across MicroPython
    ports (settimeout(0) vs setblocking(False) vs select), so the poll loop below
    is written defensively and its real yielding behaviour is device-only.
    """
    global _ntp_addr
    import socket
    try:
        import struct
    except ImportError:
        import ustruct as struct
    import utime

    if _ntp_addr is None:
        yield 'resolving'
        host = _reg('Apps.NTP_Server', '') or _NTP_HOSTS[0]
        for h in (host,) + _NTP_HOSTS:
            try:
                _ntp_addr = socket.getaddrinfo(h, 123)[0][-1]
                break
            except Exception:
                continue
        if _ntp_addr is None:
            yield False
            return

    yield 'requesting'
    pkt = bytearray(48)
    pkt[0] = 0x1B                       # LI=0, Version=3, Mode=3 (client)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg = None
    try:
        try:
            s.setblocking(False)
        except Exception:
            s.settimeout(0)
        s.sendto(pkt, _ntp_addr)
        t0 = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), t0) < timeout_ms:
            try:
                msg = s.recv(48)
                if msg:
                    break
            except Exception:
                pass                    # EAGAIN — nothing yet, come back next tick
            yield 'waiting'
    except Exception:
        msg = None
    finally:
        try:
            s.close()
        except Exception:
            pass

    if not msg or len(msg) < 44:
        _ntp_addr = None                # the cached address may be stale — re-resolve
        yield False
        return

    yield 'setting clock'
    try:
        import machine
        import time
        secs = struct.unpack('!I', msg[40:44])[0] - _ntp_epoch_delta()
        tm = time.gmtime(secs)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
    except Exception:
        yield False
        return
    try:
        write_from_rtc()                # persist to the DS3231 if one is fitted
    except Exception:
        pass
    yield True


def online_sync():
    """Blocking NTP sync — drains sync_steps(). For callers that are NOT on the
    event loop (the shell). Anything on the loop must step the generator instead,
    or it stalls the UI. Returns True on success."""
    last = None
    try:
        for last in sync_steps():
            pass
    except Exception:
        return False
    return last is True
