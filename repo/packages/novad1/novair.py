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


# --- protocol encoders: parsed (NEC/Samsung/Sony) -> raw timings -------------
def _pulsedist(data_bytes, hdr_m, hdr_s, bit, one, zero, stop=True):
    """Pulse-distance encode (NEC/Samsung family): bytes LSB-first."""
    t = [hdr_m, hdr_s]
    for byte in data_bytes:
        for i in range(8):
            t.append(bit)
            t.append(one if (byte >> i) & 1 else zero)
    if stop:
        t.append(bit)
    return t


def _hexbytes(s):
    out = []
    for tok in (s or '').split():
        try:
            out.append(int(tok, 16))
        except ValueError:
            pass
    return out


def encode(protocol, address, command):
    """Encode a parsed Flipper signal (protocol + address/command hex) to a raw
    timing list. Returns (freq, times) or None for an unsupported protocol."""
    p = (protocol or '').upper()
    a = _hexbytes(address)
    c = _hexbytes(command)
    if not a:
        a = [0]
    if not c:
        c = [0]
    if p == 'NEC':
        return 38000, _pulsedist([a[0], a[0] ^ 0xFF, c[0], c[0] ^ 0xFF],
                                 9000, 4500, 560, 1690, 560)
    if p in ('NECEXT', 'NEC_EXT', 'NEC42', 'NEC42EXT'):
        a1 = a[1] if len(a) > 1 else 0
        c1 = c[1] if len(c) > 1 else (c[0] ^ 0xFF)
        return 38000, _pulsedist([a[0], a1, c[0], c1], 9000, 4500, 560, 1690, 560)
    if p in ('SAMSUNG32', 'SAMSUNG'):
        return 38000, _pulsedist([a[0], a[0], c[0], c[0] ^ 0xFF],
                                 4500, 4500, 560, 1690, 560)
    if p in ('SIRC', 'SONY', 'SIRC15', 'SIRC20'):
        nbits = 15 if p == 'SIRC15' else (20 if p == 'SIRC20' else 12)
        if nbits == 12:
            val = (c[0] & 0x7F) | ((a[0] & 0x1F) << 7)
        elif nbits == 15:
            val = (c[0] & 0x7F) | ((a[0] & 0xFF) << 7)
        else:
            val = (c[0] & 0x7F) | ((a[0] & 0x1F) << 7) | (((a[1] if len(a) > 1 else 0) & 0xFF) << 12)
        t = [2400, 600]
        for i in range(nbits):
            t.append(1200 if (val >> i) & 1 else 600)
            t.append(600)
        return 40000, t                          # Sony uses ~40 kHz
    return None


def parse_flipper(text):
    """Return [(name, freq, duty, times)] for each signal in a .ir file — RAW
    signals use their data directly, PARSED signals (NEC/Samsung/Sony) are encoded
    to timings. Tolerant of a bare comma-separated timing list (legacy)."""
    sigs = []
    cur = {}

    def _flush():
        if not cur.get('name') and not cur.get('data'):
            return
        typ = cur.get('type', 'raw')
        if typ == 'raw' and cur.get('data'):
            sigs.append((cur.get('name', 'signal'), cur.get('freq', 38000),
                         cur.get('duty', 0.33), cur['data']))
        elif typ == 'parsed' and cur.get('protocol'):
            enc = encode(cur['protocol'], cur.get('address', ''), cur.get('command', ''))
            if enc:
                sigs.append((cur.get('name', 'signal'), enc[0], 0.33, enc[1]))
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('name:'):
            _flush()
            cur = {'name': line[5:].strip()}
        elif line.startswith('type:'):
            cur['type'] = line.split(':', 1)[1].strip()
        elif line.startswith('protocol:'):
            cur['protocol'] = line.split(':', 1)[1].strip()
        elif line.startswith('address:'):
            cur['address'] = line.split(':', 1)[1].strip()
        elif line.startswith('command:'):
            cur['command'] = line.split(':', 1)[1].strip()
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
            cur = {'name': 'signal', 'data': [int(x) for x in line.split(',') if x.strip().isdigit()]}
    _flush()
    return sigs
