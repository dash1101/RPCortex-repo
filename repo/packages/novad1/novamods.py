# Desc: Nova D1 module drivers + test functions (one per peripheral).
# File: /Packages/NovaD1/novamods.py
#
# Two kinds of test, both driven by run_test():
#   * quick tests  -> def test_x(cfg, cancel=None): return (ok_bool, [lines])
#   * long tests   -> generators: yield (None, [lines]) for progress, then a final
#                     yield (ok_bool, [lines]). They check cancel() in their loops
#                     and clean up hardware in finally, so BACK cuts them off the
#                     moment it's pressed (the GUI closes the generator).
# A single blocking C call (uos.mount, dht.measure, a TLS handshake) can't be
# cooperatively cancelled — only the polling loops are truly cancel-anytime.
#
# Drivers are thin + config-driven (pins from the registry, see novad1-wiring.md).
# MicroPython-safe: no f-strings, positional split, .format() only.

import sys


def _reg(key, default=None):
    try:
        import regedit
        v = regedit.read(key)
        return v if v not in (None, '') else default
    except Exception:
        return default


def _pin(name, default):
    try:
        return int(_reg('Apps.NovaD1_PIN_' + name, default))
    except (TypeError, ValueError):
        return default


def _machine():
    import machine
    return machine


def _spi(cfg):
    m = _machine()
    return m.SPI(1, baudrate=1000000, polarity=0, phase=0,
                 sck=m.Pin(_pin('spi_sck', 12)),
                 mosi=m.Pin(_pin('spi_mosi', 11)),
                 miso=m.Pin(_pin('spi_miso', 13)))


def _i2c():
    m = _machine()
    return m.I2C(0, scl=m.Pin(int(_reg('Apps.NovaD1_SCL', 9))),
                 sda=m.Pin(int(_reg('Apps.NovaD1_SDA', 8))), freq=400000)


def _msg_pause():
    try:
        import novamsg
        novamsg.pause()
    except Exception:
        pass


def _msg_resume():
    try:
        import novamsg
        novamsg.resume()
    except Exception:
        pass


def _ms():
    import utime
    return utime.ticks_ms()


def _since(t0):
    import utime
    return utime.ticks_diff(utime.ticks_ms(), t0)


# --- simple GPIO / sensor modules (quick, tuple-returning) -------------------
def test_buzzer(cfg, cancel=None):
    m = _machine()
    import utime
    pwm = m.PWM(m.Pin(_pin('buzzer', 40)))
    try:
        for f in (880, 1320, 1760):
            pwm.freq(f); pwm.duty_u16(20000); utime.sleep_ms(150)
        pwm.duty_u16(0)
    finally:
        pwm.deinit()
    return True, ['Buzzer', 'played 3 tones']


def test_vibration(cfg, cancel=None):
    m = _machine()
    import utime
    p = m.Pin(_pin('vibe', 41), m.Pin.OUT)
    for _ in range(2):
        p.value(1); utime.sleep_ms(250); p.value(0); utime.sleep_ms(150)
    return True, ['Vibration', 'pulsed 2x']


def test_dht11(cfg, cancel=None):
    m = _machine()
    import dht
    d = dht.DHT11(m.Pin(_pin('dht', 2)))
    d.measure()
    return True, ['DHT11', 'Temp: {} C'.format(d.temperature()),
                  'Humid: {} %'.format(d.humidity())]


def test_battery(cfg, cancel=None):
    m = _machine()
    adc = m.ADC(m.Pin(_pin('battery', 1)))
    try:
        adc.atten(m.ADC.ATTN_11DB)
    except Exception:
        pass
    raw = 0
    for _ in range(16):
        raw += adc.read_u16()
    v_adc = (raw / 16) / 65535 * 3.3
    vbat = v_adc * 2.0                      # assumes a /2 divider
    pct = int(max(0, min(100, (vbat - 3.3) / (4.2 - 3.3) * 100)))
    return True, ['Battery', '{:.2f} V'.format(vbat), '~{} %'.format(pct)]


def test_ibutton(cfg, cancel=None):
    m = _machine()
    import onewire
    ow = onewire.OneWire(m.Pin(_pin('ibutton', 1)))
    roms = ow.scan()
    if not roms:
        return False, ['iButton', 'no device', '(touch one)']
    return True, ['iButton', 'ID:', ' '.join('{:02x}'.format(b) for b in roms[0])]


def test_ir_tx(cfg, cancel=None):
    m = _machine()
    import utime
    pwm = m.PWM(m.Pin(_pin('ir_tx', 39)))
    try:
        pwm.freq(38000)
        for _ in range(10):
            pwm.duty_u16(32768); utime.sleep_us(560)
            pwm.duty_u16(0); utime.sleep_us(560)
        pwm.duty_u16(0)
    finally:
        pwm.deinit()
    return True, ['IR emitter', 'sent 38kHz burst', 'use RX to verify']


def test_sdcard(cfg, cancel=None):
    import uos
    _msg_pause()                          # SD takes over the SPI host — pause LoRa mgr
    try:
        # Prefer the OS core mount (one mount point, shared with `sd` + boot).
        try:
            import sdmgr
            okk, msg = sdmgr.mount()
            if not okk:
                return False, ['SD card', msg[:16], 'check wiring']
            files = uos.listdir('/sd')
            return True, ['SD card OK', '{} entries'.format(len(files)),
                          files[0][:16] if files else '(empty)']
        except ImportError:
            pass        # older OS without sdmgr — fall back to a direct mount
        m = _machine()
        try:
            sd = m.SDCard(slot=2, sck=m.Pin(_pin('spi_sck', 12)),
                          mosi=m.Pin(_pin('spi_mosi', 11)),
                          miso=m.Pin(_pin('spi_miso', 13)),
                          cs=m.Pin(_pin('sd_cs', 15)))
            uos.mount(sd, '/sd')
            files = uos.listdir('/sd')
            uos.umount('/sd')
            return True, ['SD card OK', '{} entries'.format(len(files)),
                          files[0][:16] if files else '(empty)']
        except Exception as e:
            return False, ['SD card', 'init failed', str(e)[:16]]
    finally:
        _msg_resume()


def test_cc1101(cfg, cancel=None):
    m = _machine()
    import utime
    _msg_pause()                          # free the shared SPI bus from the LoRa mgr
    spi = _spi(cfg)
    cs = m.Pin(_pin('cc_cs', 10), m.Pin.OUT, value=1)
    try:
        cs.value(0); utime.sleep_us(20)
        spi.write(b'\x30')                            # SRES strobe
        utime.sleep_ms(2)
        cs.value(1); utime.sleep_us(40)
        cs.value(0)
        spi.write(bytes([0x31 | 0xC0])); ver = spi.read(1)[0]    # VERSION
        spi.write(bytes([0x30 | 0xC0])); part = spi.read(1)[0]   # PARTNUM
        cs.value(1)
        if ver in (0x04, 0x14, 0x17):
            return True, ['CC1101 detected', 'ver 0x{:02x}'.format(ver),
                          'part 0x{:02x}'.format(part)]
        return False, ['CC1101', 'unexpected id', 'ver 0x{:02x}'.format(ver)]
    except Exception as e:
        return False, ['CC1101', 'SPI error', str(e)[:16]]
    finally:
        try:
            spi.deinit()
        except Exception:
            pass
        _msg_resume()


def test_sx1276(cfg, cancel=None):
    m = _machine()
    import utime
    _msg_pause()                          # the LoRa manager owns this radio — pause it
    spi = _spi(cfg)
    cs = m.Pin(_pin('sx_cs', 21), m.Pin.OUT, value=1)
    rst = m.Pin(_pin('sx_rst', 47), m.Pin.OUT, value=1)
    try:
        rst.value(0); utime.sleep_ms(2); rst.value(1); utime.sleep_ms(10)
        cs.value(0)
        spi.write(bytes([0x42 & 0x7F])); ver = spi.read(1)[0]    # RegVersion
        cs.value(1)
        if ver == 0x12:
            return True, ['SX1276 detected', 'RegVersion 0x12']
        return False, ['SX1276', 'unexpected id', 'ver 0x{:02x}'.format(ver)]
    except Exception as e:
        return False, ['SX1276', 'SPI error', str(e)[:16]]
    finally:
        try:
            spi.deinit()
        except Exception:
            pass
        _msg_resume()


# --- status LED — WS2812/NeoPixel (default) or plain GPIO (generator) --------
def test_led(cfg, cancel=None):
    cancel = cancel or (lambda: False)
    m = _machine()
    pin = _pin('led', 48)               # most ESP32-S3 devkits: onboard RGB on 48
    mode = _reg('Apps.NovaD1_LED_Mode', 'rgb')
    if mode == 'rgb':
        try:
            import neopixel
            np = neopixel.NeoPixel(m.Pin(pin, m.Pin.OUT), 1)
        except Exception as e:
            yield (False, ['Status LED', 'no NeoPixel', 'try LED_Mode gpio'])
            return
        cols = [(60, 0, 0), (0, 60, 0), (0, 0, 60), (60, 60, 0), (0, 60, 60), (60, 0, 60)]
        try:
            steps = 0
            while steps < len(cols) * 7:
                if cancel():
                    break
                if steps % 7 == 0:
                    np[0] = cols[(steps // 7) % len(cols)]; np.write()
                yield (None, ['Status LED', 'RGB pin ' + str(pin), 'cycling colors'])
                steps += 1
            yield (True, ['Status LED OK', 'RGB pin ' + str(pin), 'if dark: wrong pin'])
        finally:
            try:
                np[0] = (0, 0, 0); np.write()
            except Exception:
                pass
        return
    # plain GPIO
    p = m.Pin(pin, m.Pin.OUT)
    try:
        for i in range(12):
            if cancel():
                break
            p.value(i % 2)
            yield (None, ['Status LED', 'GPIO pin ' + str(pin), 'blinking'])
        yield (True, ['Status LED OK', 'GPIO pin ' + str(pin)])
    finally:
        try:
            p.value(0)
        except Exception:
            pass


# --- IR receive (generator, cancel-anytime) ---------------------------------
def test_ir_rx(cfg, cancel=None):
    cancel = cancel or (lambda: False)
    m = _machine()
    import utime
    p = m.Pin(_pin('ir_rx', 38), m.Pin.IN)
    t0 = _ms(); edges = 0; last = p.value()
    while _since(t0) < 6000:
        if cancel():
            return
        tb = utime.ticks_ms()                 # sample a short burst (<=18ms)
        while utime.ticks_diff(utime.ticks_ms(), tb) < 18:
            v = p.value()
            if v != last:
                edges += 1; last = v
        if edges > 16:
            yield (True, ['IR receiver', 'SIGNAL!', '{} edges'.format(edges)])
            return
        yield (None, ['IR receiver', 'point a remote', 'edges {}  {}s'.format(edges, _since(t0) // 1000)])
    if edges:
        yield (True, ['IR receiver', 'weak signal', '{} edges'.format(edges)])
    else:
        yield (False, ['IR receiver', 'no signal', 'check wiring'])


# --- GPS (generator) — prove RX even without a fix --------------------------
def test_gps(cfg, cancel=None):
    cancel = cancel or (lambda: False)
    m = _machine()
    u = m.UART(1, baudrate=9600, tx=m.Pin(_pin('gps_tx', 17)), rx=m.Pin(_pin('gps_rx', 18)))
    try:
        t0 = _ms(); buf = b''; nbytes = 0
        used = '0'           # GGA: satellites USED (0 until a fix)
        inview = '0'         # GSV: satellites IN VIEW (shows progress before a fix)
        fix = None
        while _since(t0) < 12000:
            if cancel():
                return
            while u.any():                    # drain the FIFO this step (no loss)
                d = u.read()
                if not d:
                    break
                buf += d; nbytes += len(d)
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    try:
                        s = line.decode('ascii', 'ignore')
                    except Exception:
                        continue
                    if 'GGA' in s:            # fix quality + satellites used
                        f = s.split(',')
                        if len(f) > 7:
                            if f[6] not in ('', '0'):
                                fix = (f[2], f[4])
                            used = f[7] or '0'
                    elif 'GSV' in s:          # satellites in view (pre-fix progress)
                        f = s.split(',')
                        if len(f) > 3 and f[3].strip().isdigit():
                            inview = f[3].strip()
            if fix:
                yield (True, ['GPS FIX', 'sats used: ' + used, 'lat ' + fix[0][:9], 'lon ' + fix[1][:9]])
                return
            secs = _since(t0) // 1000
            if nbytes == 0:
                yield (None, ['GPS: no data ' + str(secs) + 's', 'check TX<->RX', 'swap if still 0', 'at ~5s'])
            else:
                yield (None, ['GPS RX ok ' + str(secs) + 's', 'in view: ' + inview, 'used: ' + used, 'waiting for fix'])
        if nbytes == 0:
            yield (False, ['GPS: NO DATA', 'swap TX/RX?', 'check baud/wiring'])
        else:
            yield (True, ['GPS RX ok', 'sats in view: ' + inview, 'no fix (needs sky)', 'bytes ' + str(nbytes)])
    finally:
        try:
            u.deinit()
        except Exception:
            pass


# --- PN532 NFC (I2C) — scan-first, then proper ready-poll handshake ----------
_PN532_ADDR = 0x24


def _pn532_frame(body):
    ln = len(body)
    fr = bytearray([0x00, 0x00, 0xFF, ln, (0x100 - ln) & 0xFF])
    fr += bytes(body)
    chk = 0
    for b in body:
        chk += b
    fr += bytes([(0x100 - (chk & 0xFF)) & 0xFF, 0x00])
    return fr


def _pn532_ready(i2c, cancel, tries=40):
    import utime
    for _ in range(tries):
        if cancel():
            return False
        try:
            if i2c.readfrom(_PN532_ADDR, 1)[0] == 0x01:
                return True
        except Exception:
            pass
        utime.sleep_ms(5)
    return False


def test_pn532(cfg, cancel=None):
    cancel = cancel or (lambda: False)
    import utime
    i2c = _i2c()
    try:
        addrs = i2c.scan()
    except Exception as e:
        yield (False, ['PN532', 'I2C bus error', str(e)[:16]])
        return
    if _PN532_ADDR not in addrs:
        yield (False, ['PN532 not found', 'set DIPs to I2C', '0x24 not on bus', 'check wiring'])
        return
    yield (None, ['PN532', 'found 0x24', 'reading fw...'])
    try:
        i2c.writeto(_PN532_ADDR, _pn532_frame([0xD4, 0x02]))   # GetFirmwareVersion
        if not _pn532_ready(i2c, cancel):
            yield (False, ['PN532 0x24', 'no ACK', 'wrong mode?'])
            return
        i2c.readfrom(_PN532_ADDR, 7)                            # consume ACK
        if not _pn532_ready(i2c, cancel):
            yield (False, ['PN532 0x24', 'no response', 'after ACK'])
            return
        r = i2c.readfrom(_PN532_ADDR, 13)
        ver = '?'
        for i in range(len(r) - 4):
            if r[i] == 0xD5 and r[i + 1] == 0x03:
                ver = '{}.{}'.format(r[i + 3], r[i + 4]); break
        # poll for a tag for ~5s
        i2c.writeto(_PN532_ADDR, _pn532_frame([0xD4, 0x4A, 0x01, 0x00]))
        t0 = _ms()
        while _since(t0) < 5000:
            if cancel():
                return
            try:
                if i2c.readfrom(_PN532_ADDR, 1)[0] == 0x01:
                    i2c.readfrom(_PN532_ADDR, 7)               # ACK
                    if _pn532_ready(i2c, cancel, 8):
                        t = i2c.readfrom(_PN532_ADDR, 25)
                        uid = _pn532_uid(t)
                        if uid:
                            yield (True, ['PN532 v' + ver, 'Tag UID:', uid])
                            return
                    # re-arm a poll
                    i2c.writeto(_PN532_ADDR, _pn532_frame([0xD4, 0x4A, 0x01, 0x00]))
            except Exception:
                pass
            yield (None, ['PN532 v' + ver, 'tap a tag...', str(_since(t0) // 1000) + 's'])
        yield (True, ['PN532 v' + ver, 'detected OK', '(no tag tapped)'])
    except Exception as e:
        yield (False, ['PN532', 'error', str(e)[:16]])


def pn532_read_uid(cancel=None):
    """One bounded (~120ms) poll for a tag UID. Returns hex-UID string or None.
    Reusable by the NFC app (I2C bus; no conflict with the SPI radios)."""
    cancel = cancel or (lambda: False)
    try:
        i2c = _i2c()
        if _PN532_ADDR not in i2c.scan():
            return None
        i2c.writeto(_PN532_ADDR, _pn532_frame([0xD4, 0x4A, 0x01, 0x00]))
        if not _pn532_ready(i2c, cancel, 12):
            return None
        i2c.readfrom(_PN532_ADDR, 7)            # ACK
        if not _pn532_ready(i2c, cancel, 12):
            return None
        return _pn532_uid(i2c.readfrom(_PN532_ADDR, 25))
    except Exception:
        return None


def _pn532_uid(t):
    for i in range(len(t) - 6):
        if t[i] == 0xD5 and t[i + 1] == 0x4B and t[i + 2] >= 1:
            ulen = t[i + 7] if (i + 7) < len(t) else 0
            if 0 < ulen <= 10 and (i + 8 + ulen) <= len(t):
                return ' '.join('{:02x}'.format(b) for b in t[i + 8:i + 8 + ulen])
    return None


def _pn532_card(t):
    """Parse an InListPassiveTarget reply into {uid, atqa, sak} (bytes/int).
    Layout after the 0xD5 0x4B NbTg header: Tg, SENS_RES(2)=ATQA, SEL_RES=SAK,
    UIDLength, UID...  NOTE: ATQA byte order here is exactly what the PN532 reports;
    Flipper prints ATQA big-endian (NTAG '00 44', Classic 1K '00 04'). If a scanned
    card's ATQA comes out reversed vs a real Flipper, swap the two atqa bytes in the
    READ path (device-verified, not assumed)."""
    for i in range(len(t) - 8):
        if t[i] == 0xD5 and t[i + 1] == 0x4B and t[i + 2] >= 1:
            atqa = bytes(t[i + 4:i + 6])
            sak = t[i + 6]
            ulen = t[i + 7]
            if 0 < ulen <= 10 and (i + 8 + ulen) <= len(t):
                return {'uid': bytes(t[i + 8:i + 8 + ulen]), 'atqa': atqa, 'sak': sak}
    return None


def pn532_read_card(cancel=None):
    """One bounded poll for a full anticollision result: {uid, atqa, sak} or None.
    The basis for saving a Flipper .nfc (UID/ATQA/SAK level). Memory dump (NTAG
    pages / Classic blocks via InDataExchange) is a later increment."""
    cancel = cancel or (lambda: False)
    try:
        i2c = _i2c()
        if _PN532_ADDR not in i2c.scan():
            return None
        i2c.writeto(_PN532_ADDR, _pn532_frame([0xD4, 0x4A, 0x01, 0x00]))
        if not _pn532_ready(i2c, cancel, 12):
            return None
        i2c.readfrom(_PN532_ADDR, 7)            # ACK
        if not _pn532_ready(i2c, cancel, 12):
            return None
        return _pn532_card(i2c.readfrom(_PN532_ADDR, 25))
    except Exception:
        return None


# --- Bluetooth (BLE scan, generator) — ESP32 only ---------------------------
def test_bt(cfg, cancel=None):
    cancel = cancel or (lambda: False)
    try:
        import bluetooth
        import utime
    except ImportError:
        yield (False, ['Bluetooth', 'no BLE here', '(needs ESP32)'])
        return
    found = {}

    def _irq(event, data):
        if event == 5:                         # _IRQ_SCAN_RESULT
            a = bytes(data[1])
            if a not in found:
                found[a] = data[3]
    ble = bluetooth.BLE()
    try:
        ble.active(True)
        ble.irq(_irq)
        ble.gap_scan(5000, 30000, 30000)
        t0 = _ms()
        while _since(t0) < 5000:
            if cancel():
                break
            yield (None, ['Bluetooth', 'scanning...', '{} found'.format(len(found))])
        try:
            ble.gap_scan(None)
        except Exception:
            pass
        yield (True, ['Bluetooth', '{} BLE devices'.format(len(found)), 'scan OK'])
    finally:
        try:
            ble.active(False)
        except Exception:
            pass


# --- the registry the GUI builds apps from ----------------------------------
# (key, label, test_fn). Order = home order.
MODULES = [
    ('dht11',     'DHT11 Temp',   test_dht11),
    ('gps',       'GPS',          test_gps),
    ('pn532',     'NFC (PN532)',  test_pn532),
    ('cc1101',    'Sub-GHz',      test_cc1101),
    ('sx1276',    'LoRa',         test_sx1276),
    ('bt',        'Bluetooth',    test_bt),
    ('ir_rx',     'IR Receive',   test_ir_rx),
    ('ir_tx',     'IR Send',      test_ir_tx),
    ('ibutton',   'iButton',      test_ibutton),
    ('sdcard',    'SD Card',      test_sdcard),
    ('battery',   'Battery',      test_battery),
    ('buzzer',    'Buzzer',       test_buzzer),
    ('vibration', 'Vibration',    test_vibration),
    ('led',       'Status LED',   test_led),
]


def run_test(key, cancel=None):
    """Generator yielding (status, lines): status None=in progress, True/False=
    final. Drives both generator tests and plain (ok, lines) ones uniformly."""
    if cancel is None:
        cancel = lambda: False
    fn = None
    label = '?'
    for k, l, f in MODULES:
        if k == key:
            fn = f; label = l; break
    if fn is None:
        yield (False, ['?', 'unknown module'])
        return
    try:
        res = fn(None, cancel)
    except Exception as e:
        yield (False, [label, 'error', str(e)[:16]])
        return
    if hasattr(res, '__next__'):               # a generator test
        try:
            for item in res:
                yield item
        except Exception as e:
            yield (False, [label, 'error', str(e)[:16]])
        return
    yield res                                  # plain (ok, lines)


# --- fast presence check (boot loading-bar + the System Check app) -----------
# Only BUS devices can be auto-detected (I2C scan / SPI id / UART bytes). GPIO
# actuators (LED/buzzer/vibration/IR/iButton) can't be probed without firing
# them, so they're 'manual', never a FAIL.
_MANUAL = ('Status LED', 'Buzzer', 'Vibration', 'IR Send', 'IR Recv',
           'iButton', 'SD Card', 'Battery')


def _gps_has_data(ms=500):
    m = _machine()
    import utime
    u = m.UART(1, baudrate=9600, tx=m.Pin(_pin('gps_tx', 17)), rx=m.Pin(_pin('gps_rx', 18)))
    try:
        t0 = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), t0) < ms:
            if u.any():
                return True
            utime.sleep_ms(20)
        return False
    finally:
        try:
            u.deinit()
        except Exception:
            pass


def quickcheck(cancel=None, fast=False):
    """Generator yielding (done, total, label, status, results) per probe.
    status: 'ok' | '--' (not found) | 'na' (manual). `fast` skips the GPS probe
    (the only ~0.5s one) so the BOOT bar is near-instant; the System Check app
    runs the full set."""
    cancel = cancel or (lambda: False)
    try:
        addrs = set(_i2c().scan())
    except Exception:
        addrs = set()
    bus = [('Display', 0x3c), ('NFC', 0x24), ('RTC', 0x68)]
    spi = [('Sub-GHz', test_cc1101), ('LoRa', test_sx1276)]
    total = len(bus) + len(spi) + (0 if fast else 1)
    results = []
    i = 0
    for label, addr in bus:
        if cancel():
            return
        st = 'ok' if addr in addrs else '--'
        results.append((label, st)); i += 1
        yield (i, total, label, st, results)
    for label, fn in spi:
        if cancel():
            return
        try:
            ok, _ = fn(None)
            st = 'ok' if ok else '--'
        except Exception:
            st = '--'
        results.append((label, st)); i += 1
        yield (i, total, label, st, results)
    if not fast and not cancel():
        try:
            ok = _gps_has_data(500)
        except Exception:
            ok = False
        st = 'ok' if ok else '--'
        results.append(('GPS', st)); i += 1
        yield (i, total, 'GPS', st, results)
