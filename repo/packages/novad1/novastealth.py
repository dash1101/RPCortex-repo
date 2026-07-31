# Desc: Nova D1 stealth / incognito — the wireless kill switch.
# File: /Packages/NovaD1/novastealth.py
#
# One call takes EVERY radio down — WiFi, BLE, LoRa, sub-GHz, NFC — so the device
# can't be pinged, tracked, or fingerprinted over any frequency. This is a Nova D
# family standard: stealth mode is meant to be reachable instantly, including from
# a physical switch. Each radio is killed best-effort behind its own try/except, so
# a missing or unwired module never blocks the kill. Also holds the anti-fingerprint
# MAC randomiser.
#
# The orchestration (which radios, in what order, the flag) is pure logic and
# CPython-testable; the actual hardware calls are isolated so a host test can stub
# them. MicroPython-safe: no f-strings, positional split, .format() only.

from novacore import reg as _reg, save_reg as _save_reg

_KEY = 'Apps.NovaD1_Stealth'        # 'on' while incognito
_MAC_KEY = 'Apps.NovaD1_RandomMAC'  # 'on' -> randomise MACs at bring-up


# --------------------------------------------------------------- per-radio kills
# Each returns True if it actually silenced something, False/None otherwise. None
# of them raise — a kill switch must never fail because one radio is absent.
def _kill_wifi():
    silenced = False
    try:
        import network
        for attr in ('STA_IF', 'AP_IF'):
            iface = getattr(network, attr, None)
            if iface is None:
                continue
            try:
                w = network.WLAN(iface)
                try:
                    if w.isconnected():
                        w.disconnect()
                except Exception:
                    pass
                w.active(False)
                silenced = True
            except Exception:
                pass
    except Exception:
        pass
    # Stop the Nova connect loop so it can't quietly re-associate.
    try:
        import novawifi
        if hasattr(novawifi, 'pause'):
            novawifi.pause()
    except Exception:
        pass
    return silenced


def _kill_ble():
    try:
        import novable
        if hasattr(novable, 'stop'):
            novable.stop()
    except Exception:
        pass
    try:
        import bluetooth
        bluetooth.BLE().active(False)
        return True
    except Exception:
        return False


def _kill_lora():
    # novamsg owns the SX1276; pausing it stops RX/TX. Also sleep the radio if we
    # can reach it, so it stops listening entirely.
    ok = False
    try:
        import novamsg
        novamsg.pause()
        ok = True
        lr = getattr(novamsg, '_lora', None)
        if lr is not None and hasattr(lr, 'sleep'):
            try:
                lr.sleep()
            except Exception:
                pass
    except Exception:
        pass
    return ok


def _kill_subghz():
    # CC1101 has no persistent manager; best effort — put it to sleep if a helper
    # exists. Usually a no-op until the sub-GHz driver grows a sleep/idle call.
    try:
        import novacc
        for fn in ('sleep', 'idle', 'power_down'):
            f = getattr(novacc, fn, None)
            if callable(f):
                f()
                return True
    except Exception:
        pass
    return False


def _kill_nfc():
    try:
        import novanfc
        for fn in ('power_down', 'off', 'sleep'):
            f = getattr(novanfc, fn, None)
            if callable(f):
                f()
                return True
    except Exception:
        pass
    return False


# The kill order: the two on-board radios (WiFi, BLE) that a fresh device always
# has, then the add-on radios. Table form so it stays extensible + testable.
_RADIOS = (
    ('WiFi', _kill_wifi),
    ('BLE', _kill_ble),
    ('LoRa', _kill_lora),
    ('Sub-GHz', _kill_subghz),
    ('NFC', _kill_nfc),
)


# ------------------------------------------------------------------- public API
def active():
    """True if stealth/incognito is engaged."""
    return str(_reg(_KEY, 'off')).lower() in ('on', 'true', '1')


def kill_all():
    """Take every radio down NOW. Returns the list of radio names actually
    silenced (a missing/unwired radio is skipped). Sets the stealth flag."""
    down = []
    for name, fn in _RADIOS:
        try:
            if fn():
                down.append(name)
        except Exception:
            pass
    _save_reg(_KEY, 'on')
    return down


def restore():
    """Leave stealth: clear the flag and let the radio managers resume. Does NOT
    auto-reconnect WiFi — the user re-enables what they want. Returns True."""
    _save_reg(_KEY, 'off')
    try:
        import novawifi
        if hasattr(novawifi, 'resume'):
            novawifi.resume()
    except Exception:
        pass
    try:
        import novamsg
        novamsg.resume()
    except Exception:
        pass
    return True


def toggle():
    """Flip stealth. Returns True if now active (radios killed), False if restored."""
    if active():
        restore()
        return False
    kill_all()
    return True


# ---------------------------------------------------------- anti-fingerprinting
def mac_random_enabled():
    return str(_reg(_MAC_KEY, 'off')).lower() in ('on', 'true', '1')


def _random_mac():
    """A random locally-administered, unicast MAC (6 bytes)."""
    import uos
    mac = bytearray(uos.urandom(6))
    mac[0] = (mac[0] | 0x02) & 0xFE      # locally-administered + unicast
    return bytes(mac)


def randomize_mac():
    """Assign a fresh random MAC to the WiFi STA so a fixed MAC can't fingerprint
    the device. Call BEFORE the interface associates. Returns the MAC as a hex
    string, or None if it couldn't be set."""
    try:
        import network
        mac = _random_mac()
        network.WLAN(network.STA_IF).config(mac=mac)
        return ':'.join('{:02x}'.format(b) for b in mac)
    except Exception:
        return None


def maybe_randomize_mac():
    """Randomise the MAC only if anti-fingerprinting is enabled. Safe to call at
    every WiFi bring-up. Returns the MAC set, or None."""
    if mac_random_enabled():
        return randomize_mac()
    return None


# ------------------------------------------------------- physical switch (opt)
# A wired kill switch on Apps.NovaD1_PIN_killsw (active-low with pull-up).
# poll_edge() returns True once per press so a UI/background loop can toggle
# stealth. Inert until the pin is configured.
_sw_last = 1


def switch_pin():
    v = _reg('Apps.NovaD1_PIN_killsw', '')
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def poll_edge():
    """True exactly once on a press of the configured kill switch (falling edge).
    No-op (False) if no switch pin is configured or on any error."""
    global _sw_last
    pin = switch_pin()
    if pin is None:
        return False
    try:
        import machine
        v = machine.Pin(pin, machine.Pin.IN, machine.Pin.PULL_UP).value()
        pressed = (_sw_last == 1 and v == 0)   # falling edge = press
        _sw_last = v
        return pressed
    except Exception:
        return False
