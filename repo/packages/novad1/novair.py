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


from novacore import reg as _reg


import novaboard as _board


def _pin(name, d=None):
    """Resolve a pin through the board profile (see novaboard)."""
    return _board.pin(name, d)


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


def _merge_levels(levels):
    """Merge a (level, dur) half-bit list into a mark/space timing list. Coalesces
    adjacent same-level halves, then trims a leading idle space and a trailing space
    so the list STARTS and ENDS on a mark (what an IR TX expects)."""
    merged = []
    for lv, d in levels:
        if merged and merged[-1][0] == lv:
            merged[-1][1] += d
        else:
            merged.append([lv, d])
    if merged and merged[0][0] == 0:
        merged.pop(0)
    if merged and merged[-1][0] == 0:
        merged.pop()
    return [d for _lv, d in merged]


def _manchester(bits, half, one_low_first):
    """RC5-style bi-phase encode. one_low_first=True => logical '1' = space then mark
    (rising mid-bit), '0' = mark then space. Returns merged mark/space timings."""
    lv = []
    for b in bits:
        if (b == 1) == one_low_first:
            lv.append((0, half)); lv.append((1, half))
        else:
            lv.append((1, half)); lv.append((0, half))
    return _merge_levels(lv)


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
    if p == 'PIONEER':
        # Pioneer (common on Pioneer AV gear): NEC-family pulse-distance, LSB-first,
        # each byte followed by its complement — but Pioneer's own timing + a 40 kHz
        # carrier. TIMINGS are verbatim from the Flipper firmware header (confirmed).
        # The addr/~addr/cmd/~cmd byte LAYOUT is INFERRED (32 databits exposing an
        # 8-bit address + 8-bit command => the other 16 are the complements, the NEC
        # layout) — the round-trip test asserts the timings + bit order but NOT this
        # layout, so it's DEVICE-UNCONFIRMED against a real Pioneer remote.
        return 40000, _pulsedist([a[0], a[0] ^ 0xFF, c[0], c[0] ^ 0xFF],
                                 8500, 4225, 500, 1500, 500)
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
    if p in ('RC5', 'RC5X'):
        # Philips RC5: 14 bi-phase bits at 889 us/half, 36 kHz. Order: start1,
        # start2 (RC5X: inverted 7th command bit), toggle, 5 addr, 6 cmd (MSB first).
        addr = a[0] & 0x1F
        cmd = c[0]
        if p == 'RC5X':
            s2 = 0 if (cmd & 0x40) else 1
            cmd &= 0x3F
        else:
            s2 = 1
            cmd &= 0x3F
        bits = [1, s2, 0]                                     # start1, field, toggle=0
        bits += [(addr >> i) & 1 for i in range(4, -1, -1)]
        bits += [(cmd >> i) & 1 for i in range(5, -1, -1)]
        return 36000, _manchester(bits, 889, True)
    if p in ('RC6', 'RC6-MODE0', 'RC6_MODE0'):
        # Philips RC6 Mode 0: 2666/889 leader, then bi-phase bits at 444 us/half
        # (RC6 '1' = mark then space), 36 kHz. The toggle bit is DOUBLE width.
        # Fields: start(1), 3 mode bits (000), toggle(0), 8 addr, 8 cmd (MSB first).
        addr = a[0] & 0xFF
        cmd = c[0] & 0xFF
        bits = [1, 0, 0, 0, 0]                                # start, mode 000, toggle=0
        bits += [(addr >> i) & 1 for i in range(7, -1, -1)]
        bits += [(cmd >> i) & 1 for i in range(7, -1, -1)]
        lv = [(1, 2666), (0, 889)]                           # leader
        for i, b in enumerate(bits):
            half = 888 if i == 4 else 444                    # toggle (index 4) is 2x wide
            if b == 1:                                       # RC6 '1' = mark then space
                lv.append((1, half)); lv.append((0, half))
            else:
                lv.append((0, half)); lv.append((1, half))
        return 36000, _merge_levels(lv)
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
