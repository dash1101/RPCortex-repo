# Desc: Nova D1 infrared — raw record + replay (protocol-agnostic timing capture).
# File: /Packages/NovaD1/novair.py
#
# Records the raw mark/space durations of an IR burst (works for any protocol) and
# replays them on the emitter with a 38 kHz carrier. Codes are stored as comma-
# separated microsecond durations (times[0]=first mark, alternating), so they can
# be saved/loaded as files (and you can paste durations from online captures).
# IR is GPIO timing (no complex driver) — the most verifiable 'do' feature; the
# user's receiver already detects a real remote. MicroPython-safe: no f-strings.

_CARRIER = 38000
_DUTY = 32768
_END_GAP_US = 15000          # a >15ms idle = end of the burst
_MAX_EDGES = 400


def _reg(key, default):
    try:
        import regedit
        v = regedit.read(key)
        return v if v not in (None, '') else default
    except Exception:
        return default


def _pin(name, d):
    try:
        return int(_reg('Apps.NovaD1_PIN_' + name, d))
    except (TypeError, ValueError):
        return d


def capture(timeout_ms=8000):
    """Wait for an IR burst and return its mark/space durations (us), or None."""
    import machine
    import utime
    p = machine.Pin(_pin('ir_rx', 38), machine.Pin.IN)
    t0 = utime.ticks_ms()
    while p.value():                              # idle is high; wait for the 1st mark
        if utime.ticks_diff(utime.ticks_ms(), t0) > timeout_ms:
            return None
    times = []
    last = utime.ticks_us()
    cur = 0                                       # we just saw it go low (a mark)
    while len(times) < _MAX_EDGES:
        v = p.value()
        now = utime.ticks_us()
        if v != cur:
            times.append(utime.ticks_diff(now, last))
            last = now
            cur = v
        elif utime.ticks_diff(now, last) > _END_GAP_US:
            break                                 # long idle -> burst finished
    return times if len(times) > 4 else None


def replay(times):
    """Send a captured timing list on the emitter with the 38 kHz carrier."""
    import machine
    import utime
    pwm = machine.PWM(machine.Pin(_pin('ir_tx', 39)))
    try:
        pwm.freq(_CARRIER)
        for i in range(len(times)):
            pwm.duty_u16(_DUTY if (i % 2 == 0) else 0)   # even = mark, odd = space
            utime.sleep_us(int(times[i]))
        pwm.duty_u16(0)
    finally:
        try:
            pwm.deinit()
        except Exception:
            pass


def to_text(times):
    return ','.join(str(int(t)) for t in times)


def from_text(s):
    out = []
    for tok in s.replace('\n', ',').split(','):
        tok = tok.strip()
        if tok:
            try:
                out.append(int(tok))
            except ValueError:
                pass
    return out
