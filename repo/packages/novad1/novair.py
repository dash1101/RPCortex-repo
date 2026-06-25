# Desc: Nova D1 infrared — record + replay, Flipper-Zero .ir compatible.
# File: /Packages/NovaD1/novair.py
#
# Records raw mark/space durations of an IR burst (any protocol) and replays them
# with a 38 kHz, ~33% duty carrier, REPEATED a few times (real remotes send a
# frame 2-3x — sending it once is why the TV ignored it). Codes are stored in the
# Flipper Zero ".ir" raw format, so files interoperate both ways:
#   Filetype: IR signals file / Version: 1
#   name: <button> / type: raw / frequency: 38000 / duty_cycle: 0.330000 / data: <us...>
# A file can hold MANY named signals (a whole remote). MicroPython-safe.

_CARRIER = 38000
_DUTY33 = 21845              # ~33% of 65535 (standard IR; 50% was the bug)
_END_GAP_US = 12000
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
    """Wait for an IR burst; return its mark/space durations (us) or None."""
    import machine
    import utime
    p = machine.Pin(_pin('ir_rx', 38), machine.Pin.IN)
    t0 = utime.ticks_ms()
    while p.value():                              # idle high; wait for the 1st mark
        if utime.ticks_diff(utime.ticks_ms(), t0) > timeout_ms:
            return None
    times = []
    last = utime.ticks_us()
    cur = 0
    while len(times) < _MAX_EDGES:
        v = p.value()
        now = utime.ticks_us()
        if v != cur:
            times.append(utime.ticks_diff(now, last))
            last = now
            cur = v
        elif utime.ticks_diff(now, last) > _END_GAP_US:
            break
    return times if len(times) > 4 else None


def replay(times, freq=38000, duty=0.33, repeats=3, gap_ms=40):
    """Transmit a timing list with the carrier, repeated `repeats` times."""
    import machine
    import utime
    pwm = machine.PWM(machine.Pin(_pin('ir_tx', 39)))
    duty_u = int(max(0.1, min(0.5, duty)) * 65535)
    try:
        pwm.freq(int(freq) or _CARRIER)
        for r in range(repeats):
            for i in range(len(times)):
                pwm.duty_u16(duty_u if (i % 2 == 0) else 0)   # even=mark, odd=space
                utime.sleep_us(int(times[i]))
            pwm.duty_u16(0)
            if r < repeats - 1:
                utime.sleep_ms(gap_ms)
    finally:
        try:
            pwm.deinit()
        except Exception:
            pass


# --- Flipper .ir format -----------------------------------------------------
def to_flipper(name, times, freq=38000, duty=0.33):
    return ('Filetype: IR signals file\nVersion: 1\n#\n'
            'name: {}\ntype: raw\nfrequency: {}\nduty_cycle: {:.6f}\ndata: {}\n'
            .format(name, int(freq), duty, ' '.join(str(int(t)) for t in times)))


def append_signal(existing, name, times, freq=38000, duty=0.33):
    """Append another named raw signal to a .ir file's text (build a remote)."""
    block = ('#\nname: {}\ntype: raw\nfrequency: {}\nduty_cycle: {:.6f}\ndata: {}\n'
             .format(name, int(freq), duty, ' '.join(str(int(t)) for t in times)))
    if not existing:
        return to_flipper(name, times, freq, duty)
    if not existing.endswith('\n'):
        existing += '\n'
    return existing + block


def parse_flipper(text):
    """Return [(name, freq, duty, times)] for every RAW signal in a .ir file.
    Tolerant: a bare 'data:'-only file (our old format) still parses."""
    sigs = []
    cur = {}

    def _flush():
        if cur.get('data') and cur.get('type', 'raw') == 'raw':
            sigs.append((cur.get('name', 'signal'), cur.get('freq', 38000),
                         cur.get('duty', 0.33), cur['data']))
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('name:'):
            _flush()
            cur = {'name': line[5:].strip()}
        elif line.startswith('type:'):
            cur['type'] = line.split(':', 1)[1].strip()
        elif line.startswith('frequency:'):
            try:
                cur['freq'] = int(line.split(':', 1)[1])
            except ValueError:
                pass
        elif line.startswith('duty_cycle:'):
            try:
                cur['duty'] = float(line.split(':', 1)[1])
            except ValueError:
                pass
        elif line.startswith('data:'):
            cur['data'] = [int(x) for x in line.split(':', 1)[1].split() if x.lstrip('-').isdigit()]
        elif line and ',' in line and 'data' not in cur and not cur.get('name'):
            # legacy: a bare comma-separated timing list
            cur = {'name': 'signal', 'data': [int(x) for x in line.split(',') if x.strip().isdigit()]}
    _flush()
    return sigs
