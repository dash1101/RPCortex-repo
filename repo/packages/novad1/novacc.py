# Desc: Nova D1 CC1101 sub-GHz OOK transmit (load + fire raw timing codes).
# File: /Packages/NovaD1/novacc.py
#
# Fires a raw OOK code by bit-banging GDO0 in async-TX mode (carrier on for marks,
# off for spaces) — the same timing-list format as IR, so downloaded/edited codes
# drop straight in. EXPERIMENTAL / DEVICE-PENDING: register config follows the
# CC1101 datasheet but is unverified; needs GDO0 wired (cc_gdo0, default 14) and a
# legal frequency for your region (own/authorized devices only). MicroPython-safe.

_FREQ_MHZ = 915.0

# registers / strobes
_IOCFG0 = 0x02
_FREQ2 = 0x0D
_MDMCFG2 = 0x10
_PKTCTRL0 = 0x08
_PATABLE = 0x3E
_SRES = 0x30
_STX = 0x35
_SIDLE = 0x36


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


def _spi():
    import machine
    return machine.SPI(1, baudrate=1000000, polarity=0, phase=0,
                       sck=machine.Pin(_pin('spi_sck', 12)),
                       mosi=machine.Pin(_pin('spi_mosi', 11)),
                       miso=machine.Pin(_pin('spi_miso', 13)))


def present():
    """Quick CC1101 detect: read the VERSION status register over SPI. True if a
    chip answers (so the UI can refuse to 'transmit' into thin air)."""
    import machine
    try:
        import novamsg
        novamsg.pause()
    except Exception:
        pass
    spi = None
    try:
        spi = _spi()
        cs = machine.Pin(_pin('cc_cs', 10), machine.Pin.OUT, value=1)
        cs.value(0)
        spi.write(bytes([0x31 | 0xC0]))          # VERSION reg, burst+status read
        v = spi.read(1)[0]
        cs.value(1)
        return v not in (0x00, 0xFF)              # 0x00/0xFF = nothing on the bus
    except Exception:
        return False
    finally:
        try:
            if spi is not None:
                spi.deinit()
        except Exception:
            pass
        try:
            import novamsg
            novamsg.resume()
        except Exception:
            pass


def fire_timing(times, freq_mhz=None):
    """Transmit a raw OOK timing list (us; times[0]=first mark). Best-effort."""
    import machine
    import utime
    try:
        import novamsg
        novamsg.pause()                          # own the shared SPI bus
    except Exception:
        pass
    spi = _spi()
    cs = machine.Pin(_pin('cc_cs', 10), machine.Pin.OUT, value=1)
    gdo0 = machine.Pin(_pin('cc_gdo0', 14), machine.Pin.OUT, value=0)
    try:
        def w(a, v):
            cs.value(0); spi.write(bytes([a, v])); cs.value(1)

        def strobe(s):
            cs.value(0); spi.write(bytes([s])); cs.value(1)

        strobe(_SRES); utime.sleep_ms(2)
        f = int((freq_mhz or _FREQ_MHZ) * 1000000 / (26000000.0 / 65536))
        w(_FREQ2, (f >> 16) & 0xFF)
        w(_FREQ2 + 1, (f >> 8) & 0xFF)
        w(_FREQ2 + 2, f & 0xFF)
        w(_MDMCFG2, 0x30)                        # OOK/ASK, no sync
        w(_PKTCTRL0, 0x32)                       # async serial TX (GDO0 = data in)
        w(_IOCFG0, 0x2D)                         # GDO0 -> async serial data input
        # PATABLE: index0 = off, index1 = on (OOK power)
        cs.value(0); spi.write(bytes([_PATABLE | 0x40, 0x00, 0xC6])); cs.value(1)
        strobe(_STX)
        utime.sleep_ms(1)
        for i in range(len(times)):
            gdo0.value(1 if (i % 2 == 0) else 0)  # even = mark (carrier), odd = space
            utime.sleep_us(int(times[i]))
        gdo0.value(0)
        strobe(_SIDLE)
        return True
    except Exception:
        return False
    finally:
        try:
            spi.deinit()
        except Exception:
            pass
        try:
            import novamsg
            novamsg.resume()
        except Exception:
            pass


_DEFAULT_PRESET = 'FuriHalSubGhzPresetOok650Async'


def parse_flipper(text):
    """Parse a Flipper .sub. RAW file -> {'freq_mhz','preset','protocol':'RAW',
    'raw':[abs us...]} (raw alternates mark/space starting mark; we drop the sign,
    fire_timing re-applies the on/off pattern). Decoded Key file -> adds
    {'key','bit','te'} (replaying a decoded protocol needs a per-protocol encoder =
    a later increment; RAW covers most captures)."""
    freq_mhz = None
    preset = _DEFAULT_PRESET
    proto = ''
    raw = []
    key = None
    bit = None
    te = None
    for line in text.split('\n'):
        line = line.strip()
        if not line or line[0] == '#' or ':' not in line:
            continue
        k, v = line.split(':', 1)
        k = k.strip()
        v = v.strip()
        if k == 'Frequency':
            try:
                freq_mhz = int(v) / 1000000.0
            except ValueError:
                pass
        elif k == 'Preset':
            preset = v
        elif k == 'Protocol':
            proto = v
        elif k == 'RAW_Data':
            for tok in v.split():
                try:
                    raw.append(abs(int(tok)))
                except ValueError:
                    pass
        elif k == 'Key':
            key = v
        elif k == 'Bit':
            try:
                bit = int(v)
            except ValueError:
                pass
        elif k == 'TE':
            try:
                te = int(v)
            except ValueError:
                pass
    out = {'freq_mhz': freq_mhz, 'preset': preset, 'protocol': proto}
    if raw:
        out['raw'] = raw
    if key is not None:
        out['key'] = key
        out['bit'] = bit
        out['te'] = te
    return out


def to_flipper(name, times, freq_mhz=None, preset=None):
    """Build a Flipper RAW .sub from our abs timing list (times[0]=first mark).
    Re-applies signs (+ mark, - space), splits into <=512-value RAW_Data lines,
    frequency in Hz — exactly what a Flipper expects."""
    freq = int((freq_mhz or _FREQ_MHZ) * 1000000)
    lines = ['Filetype: Flipper SubGhz RAW File', 'Version: 1',
             'Frequency: {}'.format(freq),
             'Preset: {}'.format(preset or _DEFAULT_PRESET), 'Protocol: RAW']
    signed = []
    for i in range(len(times)):
        t = abs(int(times[i]))
        signed.append(t if (i % 2 == 0) else -t)
    i = 0
    while i < len(signed):
        lines.append('RAW_Data: ' + ' '.join(str(x) for x in signed[i:i + 512]))
        i += 512
    return '\n'.join(lines) + '\n'


def _key_to_int(key_hex):
    val = 0
    for tok in (key_hex or '').split():
        try:
            val = (val << 8) | int(tok, 16)
        except ValueError:
            pass
    return val


def _encode_princeton(val, bits, te, guard=30):
    """Princeton / PT2262 (exact, per the Flipper firmware encoder): each data bit
    MSB-first -> bit 1 = (te*3 high, te low), bit 0 = (te high, te*3 low); then a
    stop pulse te high + guard low (te*guard, default 30). Returns our abs timing
    list (alternating mark/space starting with a mark)."""
    out = []
    i = bits - 1
    while i >= 0:
        if (val >> i) & 1:
            out.append(te * 3)
            out.append(te)
        else:
            out.append(te)
            out.append(te * 3)
        i -= 1
    out.append(te)                # stop pulse (high)
    out.append(te * guard)        # guard (low)
    return out


def encode_decoded(protocol, key_hex, bits, te):
    """Encode a DECODED Flipper .sub (Protocol/Key/Bit/TE) into a raw timing list so
    it can be replayed. Princeton is supported (the most common fixed-code OOK);
    others (CAME, NICE FLO, ...) return None until added. Returns timings or None."""
    if not te or not bits:
        return None
    p = (protocol or '').strip().lower()
    if p == 'princeton':
        return _encode_princeton(_key_to_int(key_hex), bits, te)
    return None


def _timings_from(text):
    """Extract (timings, freq_mhz) from a Flipper RAW .sub, a DECODED Key-file .sub
    (Princeton encoded to timings), OR our plain timing list. (None, None) if not
    replayable (e.g. an unsupported decoded protocol)."""
    if 'Filetype: Flipper SubGhz' in text or 'RAW_Data:' in text:
        d = parse_flipper(text)
        if d.get('raw'):
            return d['raw'], d.get('freq_mhz')
        enc = encode_decoded(d.get('protocol'), d.get('key'), d.get('bit'), d.get('te'))
        if enc:
            return enc, d.get('freq_mhz')
        return None, None
    out = []
    for tok in text.replace('\n', ',').split(','):
        tok = tok.strip()
        if tok:
            try:
                out.append(int(tok))
            except ValueError:
                pass
    return (out or None), None


def fire_text(text, freq_mhz=None, repeats=1, cancel=None):
    """Fire a saved sub-GHz code: a Flipper RAW .sub, a DECODED Key-file .sub
    (Princeton is encoded to timings; other protocols not yet -> False), OR our plain
    timing list. `repeats` re-sends the burst (many remotes need 3-5x); `cancel()` is
    checked BETWEEN bursts so a long/repeated TX can be aborted (a single burst is too
    timing-critical to interrupt mid-air)."""
    timings, ffreq = _timings_from(text)
    if not timings:
        return False
    cancel = cancel or (lambda: False)
    fired = False
    for _ in range(max(1, int(repeats))):
        if cancel():
            break
        fired = fire_timing(timings, freq_mhz or ffreq) or fired
    return fired
