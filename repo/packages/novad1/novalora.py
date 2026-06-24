# Desc: Nova D1 SX1276 LoRa driver — init / send / receive (carries mesh packets).
# File: /Packages/NovaD1/novalora.py
#
# Minimal SX127x LoRa driver for P2P comms (novamesh frames ride on top). Pins +
# frequency are config-driven (Apps.NovaD1_PIN_sx_*, Apps.NovaD1_LoRa_Freq MHz,
# default 915). DEVICE-PENDING: register logic follows the SX1276 datasheet but
# has only been desk-checked — verify on hardware (and you need TWO boards to test
# actual comms). All radio access is try-excepted by callers. MicroPython-safe.

# SX127x LoRa registers
_FIFO = 0x00
_OPMODE = 0x01
_FRMSB = 0x06
_PACFG = 0x09
_LNA = 0x0C
_FIFO_PTR = 0x0D
_FIFO_TX = 0x0E
_FIFO_RX = 0x0F
_FIFO_RXCUR = 0x10
_IRQ = 0x12
_RXNB = 0x13
_PKTRSSI = 0x1A
_MCFG1 = 0x1D
_MCFG2 = 0x1E
_PRE_MSB = 0x20
_PAYLEN = 0x22
_MCFG3 = 0x26
_DIO1 = 0x40
_VERSION = 0x42
_PADAC = 0x4D

_LORA = 0x80
_SLEEP = 0x00
_STDBY = 0x01
_TX = 0x03
_RXCONT = 0x05

_IRQ_TXDONE = 0x08
_IRQ_RXDONE = 0x40
_IRQ_CRCERR = 0x20


def _reg(key, default):
    try:
        import regedit
        v = regedit.read(key)
        return v if v not in (None, '') else default
    except Exception:
        return default


def _pin(key, d):
    try:
        return int(_reg(key, d))
    except (TypeError, ValueError):
        return d


class LoRa:
    def __init__(self):
        import machine
        self._m = machine
        self.spi = machine.SPI(1, baudrate=2000000, polarity=0, phase=0,
                               sck=machine.Pin(_pin('Apps.NovaD1_PIN_spi_sck', 12)),
                               mosi=machine.Pin(_pin('Apps.NovaD1_PIN_spi_mosi', 11)),
                               miso=machine.Pin(_pin('Apps.NovaD1_PIN_spi_miso', 13)))
        self.cs = machine.Pin(_pin('Apps.NovaD1_PIN_sx_cs', 21), machine.Pin.OUT, value=1)
        rstn = _pin('Apps.NovaD1_PIN_sx_rst', 47)
        self.rst = machine.Pin(rstn, machine.Pin.OUT, value=1) if rstn >= 0 else None
        self._rx_armed = False

    def _w(self, addr, val):
        self.cs.value(0)
        self.spi.write(bytes([addr | 0x80, val & 0xFF]))
        self.cs.value(1)

    def _r(self, addr):
        self.cs.value(0)
        self.spi.write(bytes([addr & 0x7F]))
        v = self.spi.read(1)[0]
        self.cs.value(1)
        return v

    def reset(self):
        import utime
        if self.rst is not None:
            self.rst.value(0); utime.sleep_ms(2)
            self.rst.value(1); utime.sleep_ms(10)

    def begin(self):
        """Returns True if the chip answers with the expected version (0x12)."""
        import utime
        self.reset()
        if self._r(_VERSION) != 0x12:
            return False
        self._w(_OPMODE, _LORA | _SLEEP); utime.sleep_ms(10)
        # frequency
        try:
            mhz = float(_reg('Apps.NovaD1_LoRa_Freq', '915'))
        except (TypeError, ValueError):
            mhz = 915.0
        frf = int(mhz * 1000000 / 61.03515625)
        self._w(_FRMSB, (frf >> 16) & 0xFF)
        self._w(_FRMSB + 1, (frf >> 8) & 0xFF)
        self._w(_FRMSB + 2, frf & 0xFF)
        # base addrs, LNA boost
        self._w(_FIFO_TX, 0x00)
        self._w(_FIFO_RX, 0x00)
        self._w(_LNA, self._r(_LNA) | 0x03)
        # modem: BW125kHz (0x7), CR4/5 (0x1), explicit header -> 0x72; SF7 + CRC on
        self._w(_MCFG1, 0x72)
        self._w(_MCFG2, 0x74)
        self._w(_MCFG3, 0x04)             # LowDataRateOptimize off, AgcAutoOn
        self._w(_PRE_MSB, 0x00)
        self._w(_PRE_MSB + 1, 0x08)       # preamble length 8
        # PA: PA_BOOST, ~17 dBm
        self._w(_PACFG, 0x8F)
        self._w(_PADAC, 0x84)
        self._w(_OPMODE, _LORA | _STDBY); utime.sleep_ms(5)
        return True

    def send(self, data, timeout_ms=2000):
        import utime
        self._rx_armed = False
        self._w(_OPMODE, _LORA | _STDBY)
        self._w(_IRQ, 0xFF)               # clear IRQs
        self._w(_FIFO_PTR, 0x00)
        self.cs.value(0)
        self.spi.write(bytes([_FIFO | 0x80]))
        self.spi.write(bytes(data))
        self.cs.value(1)
        self._w(_PAYLEN, len(data) & 0xFF)
        self._w(_OPMODE, _LORA | _TX)
        t0 = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), t0) < timeout_ms:
            if self._r(_IRQ) & _IRQ_TXDONE:
                self._w(_IRQ, 0xFF)
                return True
            utime.sleep_ms(5)
        return False

    def start_rx(self):
        self._w(_IRQ, 0xFF)
        self._w(_FIFO_PTR, 0x00)
        self._w(_OPMODE, _LORA | _RXCONT)
        self._rx_armed = True

    def poll(self):
        """Non-blocking: return received bytes (CRC ok) or None."""
        if not self._rx_armed:
            self.start_rx()
        flags = self._r(_IRQ)
        if not (flags & _IRQ_RXDONE):
            return None
        self._w(_IRQ, 0xFF)
        if flags & _IRQ_CRCERR:
            return None
        n = self._r(_RXNB)
        self._w(_FIFO_PTR, self._r(_FIFO_RXCUR))
        self.cs.value(0)
        self.spi.write(bytes([_FIFO & 0x7F]))
        data = self.spi.read(n)
        self.cs.value(1)
        return bytes(data)

    def rssi(self):
        try:
            return self._r(_PKTRSSI) - 157
        except Exception:
            return 0

    def sleep(self):
        try:
            self._w(_OPMODE, _LORA | _SLEEP)
        except Exception:
            pass
