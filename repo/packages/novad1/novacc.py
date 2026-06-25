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


def fire_text(text, freq_mhz=None):
    from_text = []
    for tok in text.replace('\n', ',').split(','):
        tok = tok.strip()
        if tok:
            try:
                from_text.append(int(tok))
            except ValueError:
                pass
    if not from_text:
        return False
    return fire_timing(from_text, freq_mhz)
