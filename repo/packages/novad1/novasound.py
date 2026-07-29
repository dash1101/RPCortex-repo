# Desc: Nova D1 sound — a short, clean boot chime on the buzzer (PWM).
# File: /Packages/NovaD1/novasound.py
#
# A futuristic rising arpeggio. Config-gated (Apps.NovaD1_Chime, default on) and
# fully try-excepted: the buzzer may be unwired, so this must NEVER block boot for
# long or raise. Buzzer pin from Apps.NovaD1_PIN_buzzer (default 40).
# MicroPython-safe: no f-strings.

# A clean rising figure: C6, E6, G6, C7 (bright, short, "powering up").
_CHIME = ((1047, 60), (1319, 60), (1568, 60), (2093, 110))


from novacore import reg as _reg
import novaboard as _board


def _pin(name, d=None):
    """Resolve a pin through the board profile (see novaboard)."""
    return _board.pin(name, d)


def chime():
    """Play the boot chime if enabled. Returns quickly; never raises."""
    if str(_reg('Apps.NovaD1_Chime', 'on')).lower() in ('off', 'false', '0'):
        return
    try:
        import machine
        import utime
    except Exception:
        return
    pin = _pin('buzzer', 40)
    pwm = None
    try:
        pwm = machine.PWM(machine.Pin(pin))
        for freq, ms in _CHIME:
            pwm.freq(freq)
            pwm.duty_u16(18000)
            utime.sleep_ms(ms)
        pwm.duty_u16(0)
    except Exception:
        pass
    finally:
        try:
            if pwm is not None:
                pwm.duty_u16(0)
                pwm.deinit()
        except Exception:
            pass
