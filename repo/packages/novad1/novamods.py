# Desc: Nova D1 module drivers + test functions (one per peripheral).
# File: /Packages/NovaD1/novamods.py
#
# Each module exposes test(cfg) -> (ok_bool, [lines]) doing the minimal
# demonstrable thing for the GUI test app. Drivers are deliberately thin + config-
# driven (pins from the registry, see novad1-wiring.md). FIRST CUT — written
# without the panel; the simple GPIO/sensor ones are high-confidence, the SPI/I2C
# RF + NFC ones are detect-first and may need on-wire iteration.
#
# MicroPython-safe: no f-strings, positional split, .format() only.

import sys


def _reg(key, default=None):
    try:
        import regedit
        v = regedit.read(key)
        return v if v else default
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
                 sda=m.Pin(int(_reg('Apps.NovaD1_SDA', 8))))


# --- simple GPIO / sensor modules (high confidence) -------------------------
def test_led(cfg):
    m = _machine()
    p = m.Pin(_pin('led', 42), m.Pin.OUT)
    import utime
    for _ in range(6):
        p.value(1); utime.sleep_ms(120); p.value(0); utime.sleep_ms(120)
    return True, ['Status LED', 'blinked 6x OK']


def test_buzzer(cfg):
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


def test_vibration(cfg):
    m = _machine()
    import utime
    p = m.Pin(_pin('vibe', 41), m.Pin.OUT)
    for _ in range(2):
        p.value(1); utime.sleep_ms(250); p.value(0); utime.sleep_ms(150)
    return True, ['Vibration', 'pulsed 2x']


def test_dht11(cfg):
    m = _machine()
    import dht
    d = dht.DHT11(m.Pin(_pin('dht', 2)))
    d.measure()
    return True, ['DHT11', 'Temp: {} C'.format(d.temperature()),
                  'Humidity: {} %'.format(d.humidity())]


def test_battery(cfg):
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


def test_ibutton(cfg):
    m = _machine()
    import onewire
    ow = onewire.OneWire(m.Pin(_pin('ibutton', 1)))
    roms = ow.scan()
    if not roms:
        return False, ['iButton', 'no device', '(touch one to read)']
    r = roms[0]
    return True, ['iButton', 'ID:', ' '.join('{:02x}'.format(b) for b in r)]


# --- IR ---------------------------------------------------------------------
def test_ir_rx(cfg):
    m = _machine()
    import utime
    p = m.Pin(_pin('ir_rx', 38), m.Pin.IN)
    # wait up to ~4s for activity (idle is high on most receivers)
    t0 = utime.ticks_ms()
    edges = 0
    last = p.value()
    while utime.ticks_diff(utime.ticks_ms(), t0) < 4000:
        v = p.value()
        if v != last:
            edges += 1
            last = v
        if edges > 12:
            return True, ['IR receiver', 'signal received!', '{} edges'.format(edges)]
    if edges:
        return True, ['IR receiver', 'weak signal', '{} edges'.format(edges)]
    return False, ['IR receiver', 'point a remote', 'and press a key']


def test_ir_tx(cfg):
    m = _machine()
    import utime
    pwm = m.PWM(m.Pin(_pin('ir_tx', 39)))
    try:
        pwm.freq(38000)
        for _ in range(10):                 # a crude 38kHz burst train
            pwm.duty_u16(32768); utime.sleep_us(560)
            pwm.duty_u16(0); utime.sleep_us(560)
        pwm.duty_u16(0)
    finally:
        pwm.deinit()
    return True, ['IR emitter', 'sent a 38kHz burst', '(use the RX app to test)']


# --- SD card (SPI) ----------------------------------------------------------
def test_sdcard(cfg):
    m = _machine()
    import uos
    try:
        sd = m.SDCard(slot=2, sck=m.Pin(_pin('spi_sck', 12)),
                      mosi=m.Pin(_pin('spi_mosi', 11)),
                      miso=m.Pin(_pin('spi_miso', 13)),
                      cs=m.Pin(_pin('sd_cs', 15)))
    except Exception as e:
        return False, ['SD card', 'init failed:', str(e)[:18]]
    try:
        uos.mount(sd, '/sd')
        files = uos.listdir('/sd')
        uos.umount('/sd')
        return True, ['SD card', '{} entries'.format(len(files)),
                      files[0][:18] if files else '(empty)']
    except Exception as e:
        return False, ['SD card', 'mount failed:', str(e)[:18]]


# --- GPS (UART) -------------------------------------------------------------
def test_gps(cfg):
    m = _machine()
    import utime
    u = m.UART(1, baudrate=9600, tx=m.Pin(_pin('gps_tx', 17)),
               rx=m.Pin(_pin('gps_rx', 18)))
    t0 = utime.ticks_ms()
    buf = b''
    fix = None
    sats = '0'
    while utime.ticks_diff(utime.ticks_ms(), t0) < 5000:
        if u.any():
            buf += u.read()
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                try:
                    s = line.decode('ascii', 'ignore')
                except Exception:
                    continue
                if 'GGA' in s:
                    f = s.split(',')
                    if len(f) > 7:
                        if f[6] not in ('', '0'):
                            fix = (f[2], f[4])     # lat, lon (raw NMEA)
                        sats = f[7] or '0'
        if fix:
            return True, ['GPS', 'FIX  sats: ' + sats,
                          'lat ' + fix[0][:9], 'lon ' + fix[1][:9]]
        utime.sleep_ms(50)
    return False, ['GPS', 'no fix yet', 'sats seen: ' + sats, '(needs sky view)']


# --- PN532 NFC (I2C) — detect + read tag UID --------------------------------
_PN532_ADDR = 0x24


def _pn532_cmd(i2c, body):
    import utime
    ln = len(body)
    frame = bytearray([0x00, 0x00, 0xFF, ln, (0x100 - ln) & 0xFF])
    frame += bytes(body)
    chk = 0
    for b in body:
        chk += b
    frame += bytes([(0x100 - (chk & 0xFF)) & 0xFF, 0x00])
    i2c.writeto(_PN532_ADDR, frame)
    utime.sleep_ms(50)


def _pn532_read(i2c, n):
    import utime
    utime.sleep_ms(20)
    return i2c.readfrom(_PN532_ADDR, n)


def test_pn532(cfg):
    i2c = _i2c()
    try:
        _pn532_cmd(i2c, [0xD4, 0x02])                 # GetFirmwareVersion
        r = _pn532_read(i2c, 13)
        # find the firmware byte after the response code 0xD5 0x03
        ver = '?'
        for i in range(len(r) - 2):
            if r[i] == 0xD5 and r[i + 1] == 0x03:
                ver = '{}.{}'.format(r[i + 3], r[i + 4])
                break
        # try one InListPassiveTarget (106kbps type A)
        _pn532_cmd(i2c, [0xD4, 0x4A, 0x01, 0x00])
        import utime
        utime.sleep_ms(120)
        t = _pn532_read(i2c, 24)
        uid = None
        for i in range(len(t) - 6):
            if t[i] == 0xD5 and t[i + 1] == 0x4B and t[i + 2] >= 1:
                ulen = t[i + 7] if (i + 7) < len(t) else 0
                if 0 < ulen <= 10 and (i + 8 + ulen) <= len(t):
                    uid = t[i + 8:i + 8 + ulen]
                break
        if uid:
            return True, ['PN532 v' + ver, 'Tag UID:',
                          ' '.join('{:02x}'.format(b) for b in uid)]
        return True, ['PN532 v' + ver, 'detected OK', '(no tag present)']
    except Exception as e:
        return False, ['PN532', 'no response', str(e)[:18]]


# --- CC1101 sub-GHz (SPI) — detect via version register ---------------------
def test_cc1101(cfg):
    m = _machine()
    import utime
    spi = _spi(cfg)
    cs = m.Pin(_pin('cc_cs', 10), m.Pin.OUT, value=1)
    try:
        cs.value(0); utime.sleep_us(20)
        spi.write(b'\x30')                            # SRES strobe
        utime.sleep_ms(2)
        cs.value(1); utime.sleep_us(40)
        cs.value(0)
        spi.write(bytes([0x31 | 0xC0]))               # VERSION (burst/status read)
        ver = spi.read(1)[0]
        spi.write(bytes([0x30 | 0xC0]))               # PARTNUM
        part = spi.read(1)[0]
        cs.value(1)
        if ver in (0x04, 0x14, 0x17):
            return True, ['CC1101', 'detected!', 'ver 0x{:02x} part 0x{:02x}'.format(ver, part)]
        return False, ['CC1101', 'unexpected id', 'ver 0x{:02x}'.format(ver)]
    except Exception as e:
        return False, ['CC1101', 'SPI error', str(e)[:18]]
    finally:
        try:
            spi.deinit()
        except Exception:
            pass


# --- SX1276 LoRa (SPI) — detect via RegVersion (expect 0x12) ----------------
def test_sx1276(cfg):
    m = _machine()
    import utime
    spi = _spi(cfg)
    cs = m.Pin(_pin('sx_cs', 21), m.Pin.OUT, value=1)
    rst = m.Pin(_pin('sx_rst', 47), m.Pin.OUT, value=1)
    try:
        rst.value(0); utime.sleep_ms(2); rst.value(1); utime.sleep_ms(10)
        cs.value(0)
        spi.write(bytes([0x42 & 0x7F]))               # RegVersion read
        ver = spi.read(1)[0]
        cs.value(1)
        if ver == 0x12:
            return True, ['SX1276', 'detected!', 'RegVersion 0x12']
        return False, ['SX1276', 'unexpected id', 'ver 0x{:02x}'.format(ver)]
    except Exception as e:
        return False, ['SX1276', 'SPI error', str(e)[:18]]
    finally:
        try:
            spi.deinit()
        except Exception:
            pass


# --- the registry the GUI builds apps from ----------------------------------
# (key, label, test_fn). Order = home-menu order.
MODULES = [
    ('dht11',     'DHT11 Temp',   test_dht11),
    ('gps',       'GPS',          test_gps),
    ('pn532',     'NFC (PN532)',  test_pn532),
    ('cc1101',    'Sub-GHz',      test_cc1101),
    ('sx1276',    'LoRa',         test_sx1276),
    ('ir_rx',     'IR Receive',   test_ir_rx),
    ('ir_tx',     'IR Send',      test_ir_tx),
    ('ibutton',   'iButton',      test_ibutton),
    ('sdcard',    'SD Card',      test_sdcard),
    ('battery',   'Battery',      test_battery),
    ('buzzer',    'Buzzer',       test_buzzer),
    ('vibration', 'Vibration',    test_vibration),
    ('led',       'Status LED',   test_led),
]


def run_test(key):
    for k, label, fn in MODULES:
        if k == key:
            try:
                return fn(None)
            except Exception as e:
                return False, [label, 'error:', str(e)[:18]]
    return False, ['?', 'unknown module']
