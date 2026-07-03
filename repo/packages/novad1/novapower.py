# Desc: Nova D1 power — battery %, USB-power detect, low-battery flag (cached).
# File: /Packages/NovaD1/novapower.py
#
# Reads ONLY when the relevant pin is configured, so an unwired/floating ADC can
# never produce a lying battery icon or a spurious low-power popup:
#   Apps.NovaD1_PIN_battery -> ADC pin through a divider (Apps.NovaD1_BattDiv, def 2.0)
#   Apps.NovaD1_PIN_vbus    -> a VBUS-sense GPIO (high = on USB).  No pin = unknown.
# A reading outside 2.5..4.6 V is treated as 'no battery' (floating input). Cached
# ~5s so the status bar doesn't hammer the ADC every frame. MicroPython-safe.

_cache = {'t': None, 'd': None}
_EMPTY = {'have': False, 'pct': 0, 'volts': 0.0, 'usb': None, 'low': False}


from novacore import reg as _reg


def _pinnum(key):
    v = _reg(key, '')
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _read_raw():
    d = dict(_EMPTY)
    import machine
    bp = _pinnum('Apps.NovaD1_PIN_battery')
    if bp is not None:
        try:
            adc = machine.ADC(machine.Pin(bp))
            try:
                adc.atten(machine.ADC.ATTN_11DB)
            except Exception:
                pass
            raw = 0
            for _ in range(8):
                raw += adc.read_u16()
            v = (raw / 8) / 65535 * 3.3
            try:
                div = float(_reg('Apps.NovaD1_BattDiv', '2.0'))
            except (TypeError, ValueError):
                div = 2.0
            volts = v * div
            if 2.5 <= volts <= 4.6:               # plausible LiPo range
                d['have'] = True
                d['volts'] = volts
                d['pct'] = int(max(0, min(100, (volts - 3.3) / (4.2 - 3.3) * 100)))
        except Exception:
            pass
    vp = _pinnum('Apps.NovaD1_PIN_vbus')
    if vp is not None:
        try:
            d['usb'] = bool(machine.Pin(vp, machine.Pin.IN).value())
        except Exception:
            d['usb'] = None
    try:
        low_th = int(_reg('Apps.NovaD1_LowPct', '15'))
    except (TypeError, ValueError):
        low_th = 15
    d['low'] = d['have'] and d['pct'] < low_th and (d['usb'] is not True)
    return d


def read():
    try:
        import utime
        now = utime.ticks_ms()
    except Exception:
        return _read_raw()
    if _cache['d'] is None or _cache['t'] is None or utime.ticks_diff(now, _cache['t']) > 5000:
        try:
            _cache['d'] = _read_raw()
        except Exception:
            _cache['d'] = dict(_EMPTY)
        _cache['t'] = now
    return _cache['d']
