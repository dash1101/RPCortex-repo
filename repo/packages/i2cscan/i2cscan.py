# Desc: I2CScan — scan the I2C bus and identify devices
# File: /Packages/I2CScan/i2cscan.py
# Version: 1.0.0
# Author: dash1101
#
# Probes an I2C bus and lists responding addresses, naming common devices.
# Uses SoftI2C so it works on any two GPIO pins on RP2040/RP2350/ESP32.
#
# Usage:
#   i2cscan                  scan with the default pins
#   i2cscan <scl> <sda>      scan using the given SCL and SDA GPIO numbers
#   i2c     <scl> <sda>      alias
#
# Examples:
#   i2cscan            (defaults: SCL=GP5, SDA=GP4 on RP2; check yours)
#   i2cscan 22 21      (typical ESP32 default pins)

import sys

if '/Core' not in sys.path:
    sys.path.append('/Core')

from RPCortex import error, info, ok, warn, multi


# Default pins per platform — best-effort common choices.
def _default_pins():
    if sys.platform == 'esp32':
        return 22, 21      # ESP32 common I2C0
    return 5, 4            # RP2 common I2C0 (SCL=GP5, SDA=GP4)


# A small table of frequently-seen I2C devices.  Many addresses are shared by
# several parts, so these are hints, not certainties.
_KNOWN = {
    0x0C: "AK8963 magnetometer",
    0x10: "VEML6075 / VEML7700",
    0x1E: "HMC5883L magnetometer",
    0x20: "PCF8574 / MCP23017 I/O",
    0x23: "BH1750 light sensor",
    0x27: "PCF8574 LCD backpack",
    0x29: "VL53L0X / TSL2561",
    0x36: "MAX17048 fuel gauge",
    0x38: "AHT10 / FT6236 touch",
    0x39: "TSL2561 light sensor",
    0x3C: "SSD1306 OLED",
    0x3D: "SSD1306 OLED",
    0x40: "INA219 / PCA9685 / HTU21D",
    0x44: "SHT3x humidity",
    0x48: "ADS1115 / PCF8591 / LM75",
    0x4A: "SGP30 gas sensor",
    0x50: "AT24Cxx EEPROM",
    0x53: "ADXL345 accelerometer",
    0x57: "MAX30102 / AT24C",
    0x5A: "MLX90614 IR temp / CCS811",
    0x68: "MPU6050 / DS3231 / DS1307",
    0x69: "MPU6050 (alt) / ITG3200",
    0x76: "BME280 / BMP280",
    0x77: "BME280 / BMP180 (alt)",
}


def i2cscan(args=None):
    scl_n, sda_n = _default_pins()

    if args and args.strip():
        parts = args.split()
        if len(parts) >= 2:
            try:
                scl_n = int(parts[0])
                sda_n = int(parts[1])
            except ValueError:
                error("Pins must be numbers: i2cscan <scl> <sda>")
                return
        else:
            error("Usage: i2cscan <scl> <sda>   (or bare 'i2cscan' for defaults)")
            return

    try:
        from machine import Pin, SoftI2C
    except ImportError:
        error("machine.SoftI2C not available on this build.")
        return

    info("Scanning I2C  (SCL=GP{}, SDA=GP{})...".format(scl_n, sda_n))
    try:
        bus = SoftI2C(scl=Pin(scl_n), sda=Pin(sda_n))
        found = bus.scan()
    except Exception as e:
        error("I2C init/scan failed: {}".format(e))
        info("Override pins with: i2cscan <scl> <sda>")
        return

    if not found:
        warn("No I2C devices found.")
        multi("  Check wiring, pull-up resistors, and that the pins are correct.")
        multi("  Override pins with: i2cscan <scl> <sda>")
        return

    multi("  {:<8} {:<6} {}".format("ADDR", "DEC", "LIKELY DEVICE"))
    multi("  " + "-" * 44)
    for addr in found:
        name = _KNOWN.get(addr, "")
        multi("  0x{:02X}     {:<6} {}".format(addr, addr, name))
    multi("")
    ok("{} device(s) found.".format(len(found)))
