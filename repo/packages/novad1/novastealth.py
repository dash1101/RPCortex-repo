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
def blocked():
    """True while ANY hard stop is engaged — this package's incognito flag, or the
    OS-wide radio lock (`radio off`).

    Nova D1 radio entry points consult this and refuse. It is a second line of
    defence, not the only one: the enforcement that actually matters lives in
    net.py, because a latch only this package checks is a latch the shell can walk
    straight past, which is exactly what happened."""
    if active():
        return True
    try:
        import RPCortex as _R
        return _R.radio_locked()
    except Exception:
        return False


def _kill_wifi(hard=False):
    """Take WiFi down. With hard=True, POWER THE RADIO CHIP OFF.

    active(False) leaves the CYW43 powered and its driver running — enough to
    stop associating, not enough to call the device radio-silent. deinit() runs
    cyw43_deinit(), which drops the SDIO bus and cuts power to the WL chip, so
    there is nothing left to emit. It is recoverable: the next active(True)
    goes through cyw43_ensure_up(), which re-powers and re-initialises.

    On a Pico W the CYW43 also drives the onboard LED and the VSYS sense line,
    so both stop working while the chip is down. That is the price of the chip
    genuinely being off, and it is the honest signal that it worked.
    """
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
                try:
                    w.config(pm=0xa11140)      # best-effort: stop background scans
                except Exception:
                    pass
                w.active(False)
                silenced = True
                if hard:
                    try:
                        w.deinit()             # power the chip down
                    except Exception:
                        pass
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
    """Take every radio down NOW and LOCK them down. Returns the names actually
    silenced (a missing or unwired radio is skipped).

    The OS-level lock is what makes this stick. Previously this package held its
    own latch and only Nova D1 code consulted it, so `wifi scan` from the shell
    walked straight past incognito and brought the radio back up — the reported
    "incognito still lets me scan and connect". RPCortex.lock_radios() puts the
    latch underneath net.py, where every caller has to pass it."""
    down = []
    for name, fn in _RADIOS:
        try:
            if fn():
                down.append(name)
        except Exception:
            pass
    _save_reg(_KEY, 'on')
    try:
        import RPCortex as _R
        _R.lock_radios(True)          # the OS-wide hard stop
    except Exception:
        pass
    return down


def restore():
    """Leave stealth: release the lock and let the radio managers resume. Does NOT
    auto-reconnect WiFi — the user re-enables what they want. Returns True."""
    _save_reg(_KEY, 'off')
    try:
        import RPCortex as _R
        _R.lock_radios(False)
    except Exception:
        pass
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
    """Default ON.

    Your MAC address is the one identifier you cannot change by behaving
    differently — it is broadcast in the clear by every association, and it is
    what lets a network recognise the same device across visits. Phones have
    randomised theirs by default for years, for exactly this reason. Making it
    opt-out rather than opt-in means the device is not trackable by default; the
    cost is that a network with MAC-based access control will see a new device
    each time, which is what the switch under Settings -> Security is for."""
    return str(_reg(_MAC_KEY, 'on')).lower() in ('on', 'true', '1')


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


_ADJ = ('blue', 'calm', 'dry', 'east', 'fast', 'grey', 'high', 'iron', 'jade',
        'kind', 'low', 'mild', 'north', 'old', 'pale', 'quiet', 'red', 'soft')
_NOUN = ('atlas', 'beam', 'cove', 'delta', 'echo', 'ford', 'glen', 'haze',
         'inlet', 'jetty', 'kite', 'loft', 'mesa', 'nook', 'orbit', 'pine')


def random_hostname():
    """A fresh, ordinary-looking DHCP hostname.

    This matters as much as the MAC. The hostname goes out in the clear in every
    DHCP request, and it does NOT change when the MAC does — so randomising the
    MAC while still announcing 'vela' to every network you join achieves nothing
    at all: the name alone re-links the sessions. The two have to move together,
    which is why one switch controls both.

    Deliberately mundane word pairs rather than hex: a hostname of
    'a3f91c2b' is itself distinctive, and standing out is the thing being
    avoided."""
    try:
        import uos
        rnd = uos.urandom(3)
        return '{}-{}{}'.format(_ADJ[rnd[0] % len(_ADJ)],
                                _NOUN[rnd[1] % len(_NOUN)],
                                rnd[2] % 90 + 10)
    except Exception:
        return None


def set_hostname(name):
    """Set the DHCP hostname. Returns the name set, or None."""
    if not name:
        return None
    try:
        import network
        try:
            network.hostname(name)
        except Exception:
            network.WLAN(network.STA_IF).config(hostname=name)
        return name
    except Exception:
        return None


def maybe_randomize_mac():
    """Randomise the device's network identity, if anti-fingerprinting is on.

    Both halves or neither: the MAC and the DHCP hostname are two independent
    identifiers, and leaving either fixed lets a network recognise you across
    visits regardless of the other. Safe to call at every WiFi bring-up; must run
    BEFORE the interface associates. Returns the MAC set, or None."""
    if not mac_random_enabled():
        return None
    mac = randomize_mac()
    set_hostname(random_hostname())
    return mac


# ------------------------------------------------------------------- ghost mode
def leaks():
    """Everything about this device that a third party could currently use to
    recognise it, and whether each one is closed.

    Written as an inventory rather than a boolean because "am I anonymous" has no
    single answer — it is a list of channels, and closing four of five is not
    anonymity. Returns [(name, closed, note), ...]."""
    out = []
    locked = False
    try:
        import RPCortex as _R
        locked = _R.radio_locked()
    except Exception:
        pass
    out.append(('Radios', locked,
                'silent' if locked else 'WiFi and BLE can transmit'))
    rnd = mac_random_enabled()
    out.append(('MAC', rnd, 'randomised' if rnd else 'fixed - identifies you'))
    out.append(('Hostname', rnd,
                'randomised' if rnd else 'fixed - identifies you'))
    web = str(_reg('Apps.NovaD1_Web', 'off')).lower() == 'on'
    out.append(('Web panel', not web,
                'off' if not web else 'serving on the network'))
    mesh = str(_reg('Apps.NovaD1_Mesh_Beacon', 'off')).lower() == 'on'
    out.append(('LoRa beacon', not mesh,
                'off' if not mesh else 'announcing this node'))
    # The observer is deliberately NOT listed. It only receives, and a receiver
    # emits nothing for anyone to see — putting it in a list of things that can
    # identify you would imply otherwise.
    return out


def blackout():
    """The hardest stop available: POWER THE RADIOS OFF.

    Incognito takes the interfaces down and latches them there, which stops this
    device doing anything. Blackout goes further and cuts power to the CYW43
    itself (cyw43_deinit drops the SDIO bus and powers down the WL chip), so
    there is no radio left running to emit anything at all — nothing to detect,
    however good the detector.

    Recoverable without a reboot: the next active(True) goes through
    cyw43_ensure_up(), which re-powers and re-initialises the chip. The lock
    stays engaged until you release it, so nothing does that by accident.

    Two things stop working while the chip is down, both on the Pico W, because
    the CYW43 also drives them: the onboard LED and the VSYS battery sense. If
    the LED stops responding, that is the confirmation it actually worked.

    DEVICE-UNCONFIRMED: the power-down is a driver call the host cannot exercise.
    """
    _kill_wifi(hard=True)
    for name, fn in _RADIOS:
        if name == 'WiFi':
            continue
        try:
            fn()
        except Exception:
            pass
    _save_reg(_KEY, 'on')
    try:
        import RPCortex as _R
        _R.lock_radios(True)
    except Exception:
        pass
    return True


def ghost():
    """Go completely dark: every radio powered off, every service that announces
    this device switched off, and the identity reset for next time.

    Listening is not transmitting, so the observer is left alone — a passive
    receiver emits nothing. What gets closed is everything that SPEAKS.
    """
    blackout()                              # radios POWERED DOWN + OS-wide lock
    _save_reg('Apps.NovaD1_Web', 'off')     # stop serving the control panel
    _save_reg('Apps.NovaD1_Mesh_Beacon', 'off')
    _save_reg(_MAC_KEY, 'on')               # fresh identity when radios return
    try:
        import novaweb
        if hasattr(novaweb, 'stop'):
            novaweb.stop()
    except Exception:
        pass
    try:
        import novamsg
        novamsg.pause()
    except Exception:
        pass
    return leaks()


# ------------------------------------------------------- physical switch (opt)
# A wired kill switch on Apps.NovaD1_PIN_killsw (active-low with pull-up).
# poll_edge() returns True once per press so a UI/background loop can toggle
# stealth. Inert until the pin is configured.
_sw_last = 1
_sw_pin_obj = None      # cached machine.Pin (poll_edge runs every UI loop turn)
_sw_pin_num = None


def switch_pin():
    v = _reg('Apps.NovaD1_PIN_killsw', '')
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def poll_edge():
    """True exactly once on a press of the configured kill switch (falling edge).
    No-op (False) if no switch pin is configured or on any error. The Pin object is
    cached, so calling this every UI loop turn allocates nothing."""
    global _sw_last, _sw_pin_obj, _sw_pin_num
    pin = switch_pin()
    if pin is None:
        return False
    try:
        import machine
        if _sw_pin_obj is None or _sw_pin_num != pin:
            _sw_pin_obj = machine.Pin(pin, machine.Pin.IN, machine.Pin.PULL_UP)
            _sw_pin_num = pin
        v = _sw_pin_obj.value()
        pressed = (_sw_last == 1 and v == 0)   # falling edge = press
        _sw_last = v
        return pressed
    except Exception:
        return False
