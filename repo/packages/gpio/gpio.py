# Desc: GPIO — direct pin control from the RPCortex shell
# File: /Packages/Gpio/gpio.py
# Version: 1.0.0
# Author: dash1101
#
# Drive and read GPIO pins straight from the prompt — no script needed.
# Works offline on RP2040 / RP2350 / ESP32 (pin numbers are board-specific).
#
# Usage:
#   gpio read  <pin> [up|down]   read a digital input (optional pull resistor)
#   gpio set   <pin> <high|low>  drive a digital output  (high/low/1/0/on/off)
#   gpio toggle <pin>            flip an output pin
#   gpio pwm   <pin> <0-100> [hz] PWM output at a duty percent (default 1000 Hz)
#   gpio stop  <pin>             stop PWM and release the pin
#   gpio adc   <pin>             read an analog value (raw + voltage)
#   gpio info                    show platform notes
#
# Examples:
#   gpio set 25 high      (Pico onboard LED is GP25 on the non-W Pico)
#   gpio pwm 15 50        (50% duty square wave on GP15)
#   gpio read 14 up       (read GP14 with the internal pull-up enabled)

import sys

if '/Core' not in sys.path:
    sys.path.append('/Core')

from RPCortex import error, info, ok, warn, multi


def _pin_num(s):
    # "LED" is the onboard LED on Pico W / Pico 2 W (it's on the WiFi chip, not
    # a numbered GPIO). machine.Pin("LED") handles it; on other boards it's GP25.
    if isinstance(s, str) and s.upper() == 'LED':
        return 'LED'
    try:
        return int(s)
    except (ValueError, TypeError):
        error("Pin must be a number or 'LED', got '{}'.".format(s))
        return None


def _lbl(pin):
    return 'LED' if pin == 'LED' else 'GP{}'.format(pin)


def _read(pin, pull):
    from machine import Pin
    if pull == 'up':
        p = Pin(pin, Pin.IN, Pin.PULL_UP)
    elif pull == 'down':
        p = Pin(pin, Pin.IN, Pin.PULL_DOWN)
    else:
        p = Pin(pin, Pin.IN)
    val = p.value()
    ok("{} = {}  ({})".format(_lbl(pin), val, 'HIGH' if val else 'LOW'))


def _set(pin, level):
    from machine import Pin
    level = level.lower()
    if level in ('high', '1', 'on', 'true'):
        v = 1
    elif level in ('low', '0', 'off', 'false'):
        v = 0
    else:
        error("Level must be high/low (or 1/0, on/off). Got '{}'.".format(level))
        return
    p = Pin(pin, Pin.OUT)
    p.value(v)
    ok("{} set {}".format(_lbl(pin), 'HIGH' if v else 'LOW'))


def _toggle(pin):
    from machine import Pin
    cur = Pin(pin, Pin.IN).value()
    nv = 0 if cur else 1
    Pin(pin, Pin.OUT).value(nv)
    ok("{} toggled -> {}".format(_lbl(pin), 'HIGH' if nv else 'LOW'))


def _pwm(pin, pct, freq):
    from machine import Pin, PWM
    if pct < 0 or pct > 100:
        error("Duty must be 0-100 (percent). Got {}.".format(pct))
        return
    pwm = PWM(Pin(pin))
    try:
        pwm.freq(freq)
    except Exception:
        pass   # some ports fix the frequency; duty still applies
    pwm.duty_u16(int(pct * 65535 // 100))
    ok("GP{} PWM: {}% duty @ {} Hz".format(pin, pct, freq))
    info("Release it with: gpio stop {}".format(pin))


def _stop(pin):
    from machine import Pin, PWM
    try:
        PWM(Pin(pin)).deinit()
    except Exception:
        pass
    Pin(pin, Pin.IN)   # leave the pin high-impedance
    ok("GP{} PWM stopped, pin released.".format(pin))


def _adc(pin):
    from machine import ADC, Pin
    try:
        try:
            a = ADC(Pin(pin))          # ESP32 / explicit-pin style
        except (TypeError, ValueError):
            a = ADC(pin)               # RP2 channel-number style
        raw = a.read_u16()
        volts = raw * 3.3 / 65535
        ok("GP{} ADC: {}  ({:.3f} V)".format(pin, raw, volts))
    except Exception as e:
        error("ADC read failed on pin {}: {}".format(pin, e))
        info("ADC pins are limited (RP2040: GP26-28). Check your board.")


def _info():
    info("=== GPIO ===")
    multi("  Platform : {}".format(sys.platform))
    multi("  Pin numbers are the chip GPIO numbers, not the physical header pins.")
    multi("  RP2040/RP2350 : GP0-GP28; ADC on GP26-GP28.")
    multi("  Onboard LED   : 'gpio set LED high' (Pico W / Pico 2 W use the WiFi-chip LED; plain Pico = GP25).")
    multi("  ESP32         : varies by module; check your pinout.")
    multi("")
    multi("  read <pin> [up|down] | set <pin> high|low | toggle <pin>")
    multi("  pwm <pin> <0-100> [hz] | stop <pin> | adc <pin>")


def gpio(args=None):
    if not args or not args.strip():
        _info()
        return

    parts = args.split()
    sub = parts[0].lower()

    if sub == 'info':
        _info()
        return

    if sub in ('read', 'set', 'toggle', 'pwm', 'stop', 'adc'):
        if len(parts) < 2:
            error("Usage: gpio {} <pin> ...".format(sub))
            return
        pin = _pin_num(parts[1])
        if pin is None:
            return

        try:
            if sub == 'read':
                pull = parts[2].lower() if len(parts) > 2 else None
                _read(pin, pull)
            elif sub == 'set':
                if len(parts) < 3:
                    error("Usage: gpio set <pin> <high|low>")
                    return
                _set(pin, parts[2])
            elif sub == 'toggle':
                _toggle(pin)
            elif sub == 'pwm':
                if pin == 'LED':
                    error("PWM isn't supported on the named LED pin. Use a numbered GPIO.")
                    return
                if len(parts) < 3:
                    error("Usage: gpio pwm <pin> <0-100> [hz]")
                    return
                try:
                    pct = int(parts[2])
                except ValueError:
                    error("Duty must be a whole number 0-100.")
                    return
                freq = 1000
                if len(parts) > 3:
                    try:
                        freq = int(parts[3])
                    except ValueError:
                        warn("Bad frequency — using 1000 Hz.")
                _pwm(pin, pct, freq)
            elif sub == 'stop':
                _stop(pin)
            elif sub == 'adc':
                if pin == 'LED':
                    error("ADC isn't supported on the named LED pin. Use a numbered GPIO.")
                    return
                _adc(pin)
        except Exception as e:
            error("GPIO operation failed: {}".format(e))
        return

    error("Unknown subcommand '{}'. Try 'gpio info'.".format(sub))
