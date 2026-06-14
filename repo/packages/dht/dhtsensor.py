# Desc: DHT — DHT11 / DHT22 temperature & humidity sensor reader
# File: /Packages/DHT/dht.py
# Version: 1.0.0
# Author: dash1101
#
# Reads a DHT11 or DHT22 (AM2302) one-wire temperature/humidity sensor from a
# single GPIO pin. Works offline on any board whose MicroPython build ships the
# `dht` C module (RP2040/RP2350/ESP32 standard builds all include it).
#
# Usage:
#   dht read <pin> [11|22]      read once (sensor type defaults to 22)
#   dht watch <pin> [11|22] [n] repeat every n seconds (default 2) until Ctrl+C
#   dht info                    wiring notes and supported sensors
#
# Examples:
#   dht read 15            read a DHT22 on GP15
#   dht read 16 11         read a DHT11 on GP16
#   dht watch 15 22 5      poll a DHT22 every 5 seconds
#
# Wiring: VCC->3V3, GND->GND, DATA->the GPIO you pass. A 10k pull-up between
# DATA and 3V3 is recommended for long wires (many breakout boards include one).

import sys

if '/Core' not in sys.path:
    sys.path.append('/Core')

from RPCortex import error, info, ok, warn, multi


def _make(pin, kind):
    """Construct a DHT sensor object for the given pin and type (11 or 22)."""
    try:
        import dht
    except ImportError:
        error("This MicroPython build has no 'dht' module.")
        info("DHT support is compiled in — reflash a standard build to use it.")
        return None
    from machine import Pin
    try:
        if kind == 11:
            return dht.DHT11(Pin(pin))
        return dht.DHT22(Pin(pin))
    except Exception as e:
        error("Could not init DHT{} on GP{}: {}".format(kind, pin, e))
        return None


def _read_once(sensor, pin, kind):
    """Trigger a measurement and print it. Returns True on success."""
    try:
        sensor.measure()
        t = sensor.temperature()
        h = sensor.humidity()
    except OSError as e:
        error("Read failed on GP{}: {} (check wiring / pull-up).".format(pin, e))
        return False
    except Exception as e:
        error("DHT error: {}".format(e))
        return False
    # DHT22 returns floats; DHT11 returns ints. Apply TZ-free C->F locally.
    f = t * 9.0 / 5.0 + 32.0
    ok("DHT{} GP{}:  {:.1f} C  /  {:.1f} F   |   {:.1f}% RH".format(
        kind, pin, t, f, h))
    return True


def _parse_pin(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        error("Pin must be a GPIO number, got '{}'.".format(s))
        return None


def _parse_kind(s):
    if s is None:
        return 22
    if s in ('11', '22'):
        return int(s)
    warn("Sensor type must be 11 or 22 — assuming 22.")
    return 22


def _info():
    info("=== DHT temperature / humidity ===")
    multi("  Supported : DHT11 (kind 11) and DHT22 / AM2302 (kind 22, default)")
    multi("  Platform  : {}".format(sys.platform))
    multi("")
    multi("  read  <pin> [11|22]       single reading")
    multi("  watch <pin> [11|22] [n]   poll every n seconds (default 2)")
    multi("")
    multi("  Wiring: VCC->3V3  GND->GND  DATA->GPIO  (+10k pull-up on DATA)")
    multi("  DHT11 reads whole degrees; DHT22 reads tenths and is more accurate.")
    multi("  Sensors need ~2s between reads — don't poll faster than that.")


def dht(args=None):
    if args and args.strip() and args.split()[0].lower() in ('help', '-h', '--help', '?'):
        _info()
        return
    if not args or not args.strip():
        _info()
        return

    parts = args.split()
    sub = parts[0].lower()

    if sub == 'info':
        _info()
        return

    if sub in ('read', 'watch'):
        if len(parts) < 2:
            error("Usage: dht {} <pin> [11|22]".format(sub))
            return
        pin = _parse_pin(parts[1])
        if pin is None:
            return
        kind = _parse_kind(parts[2] if len(parts) > 2 else None)
        sensor = _make(pin, kind)
        if sensor is None:
            return

        if sub == 'read':
            _read_once(sensor, pin, kind)
            return

        # watch: poll until Ctrl+C
        import utime
        interval = 2
        if len(parts) > 3:
            try:
                interval = max(2, int(parts[3]))
            except ValueError:
                warn("Bad interval — using 2s.")
        info("Polling DHT{} on GP{} every {}s — Ctrl+C to stop.".format(
            kind, pin, interval))
        try:
            while True:
                _read_once(sensor, pin, kind)
                utime.sleep(interval)
        except KeyboardInterrupt:
            info("Stopped.")
        return

    # Bare `dht <pin> [11|22]` is treated as a single read.
    pin = _parse_pin(parts[0])
    if pin is None:
        error("Unknown subcommand '{}'. Try 'dht info'.".format(sub))
        return
    kind = _parse_kind(parts[1] if len(parts) > 1 else None)
    sensor = _make(pin, kind)
    if sensor is not None:
        _read_once(sensor, pin, kind)
