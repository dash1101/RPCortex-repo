# Desc: Nova D1 BLE — scan nearby devices + advertise (incl. Apple proximity ping).
# File: /Packages/NovaD1/novable.py
#
# ESP32 BLE (the `bluetooth` module). Two capabilities:
#   * scan()       — list nearby BLE devices (MAC / RSSI / name).
#   * advertise / proximity_ping() — broadcast an advertisement. proximity_ping
#     sends an Apple "Continuity" proximity-pairing packet so a nearby iPhone shows
#     the AirPods-style "device nearby" card — point it at YOUR phone to test.
#
# DELIBERATELY NOT here: BLE *jamming* (not possible on the ESP32 — no raw PHY /
# all-channel flood — and it's illegal RF interference), and a sustained
# "spam every nearby phone" loop (that targets bystanders who didn't opt in). The
# advertise here is BOUNDED (a fixed number of seconds) and meant for your own
# devices / authorized testing. Use responsibly.
#
# Packet layout follows the documented Apple Continuity proximity-pairing format
# (manufacturer data 4C 00, type 0x07). The exact model bytes are DEVICE-VERIFY:
# which model actually pops the card varies by iOS version — try a few.
# MicroPython-safe: no f-strings, positional split, .format() only.

_IRQ_SCAN_RESULT = 5
_IRQ_SCAN_DONE = 6

# Apple proximity-pairing device model ids (2 bytes, as advertised). Pick one for
# the popup's icon/name; any of them triggers the "nearby" card on iOS.
MODELS = {
    'airpods': b'\x02\x20',
    'airpods_pro': b'\x0e\x20',
    'airpods_max': b'\x0a\x20',
    'airpods_gen2': b'\x0f\x20',
    'airpods_gen3': b'\x13\x20',
    'airpods_pro2': b'\x14\x20',
    'powerbeats_pro': b'\x0b\x20',
    'beats_studio_buds': b'\x17\x20',
}

# Google Fast Pair model ids (3 bytes) -> the Android "device nearby" pairing
# popup. These trigger the same cross-platform effect a Flipper's BLE ping does, so
# a Flipper-style "ping an Android" runs here too. DEVICE-VERIFY which id pops on a
# given Android version.
MODELS_ANDROID = {
    'headphones': b'\xcd\x82\x56',
    'pixel_buds': b'\x71\x8f\xa4',
    'bose': b'\x0e\x39\x91',
    'generic': b'\x00\x00\x07',
}


def available():
    try:
        import bluetooth  # noqa
        return True
    except ImportError:
        return False


_ble = None


def _radio():
    import bluetooth
    global _ble
    if _ble is None:
        _ble = bluetooth.BLE()
    if not _ble.active():
        _ble.active(True)
    return _ble


def _adv_name(payload):
    """Pull the device name (AD type 0x09 complete / 0x08 short) from adv data."""
    i = 0
    p = bytes(payload)
    while i + 1 < len(p):
        ln = p[i]
        if ln == 0:
            break
        t = p[i + 1]
        if t in (0x08, 0x09):
            try:
                return bytes(p[i + 2:i + 1 + ln]).decode('utf-8')
            except Exception:
                return ''
        i += 1 + ln
    return ''


def scan(ms=5000, cancel=None):
    """Scan for BLE devices for `ms`. Returns a list of dicts:
    {'mac':'aa:bb:..', 'rssi':int, 'name':str}, strongest first."""
    # Incognito latch: refuse while stealth is engaged. Killing the radio isn't
    # enough by itself — this call would just re-activate it.
    try:
        import novastealth
        if novastealth.blocked():
            return []
    except Exception:
        pass
    cancel = cancel or (lambda: False)
    import utime
    found = {}

    def _irq(event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv = data
            mac = bytes(addr)
            prev = found.get(mac)
            if prev is None or rssi > prev['rssi']:
                nm = _adv_name(adv)
                found[mac] = {'mac': ':'.join('{:02x}'.format(b) for b in mac),
                              'rssi': rssi, 'name': nm or (prev['name'] if prev else '')}

    ble = _radio()
    try:
        ble.irq(_irq)
        ble.gap_scan(ms, 30000, 30000, True)     # active scan -> get names
        t0 = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), t0) < ms:
            if cancel():
                break
            utime.sleep_ms(60)
    finally:
        try:
            ble.gap_scan(None)
        except Exception:
            pass
    out = list(found.values())
    out.sort(key=lambda d: d['rssi'], reverse=True)
    return out


MAX_RESULTS = 24        # a crowded room must not be able to fill the heap


def scan_steps(ms=4000):
    """Scan for BLE devices as a GENERATOR, yielding between polls.

    novable.scan() sleeps for its whole duration. That is fine for a foreground
    screen that has nothing else to do, but a BACKGROUND observer using it would
    freeze the UI for seconds at a time — the same way the NTP sync did before it
    was stepped. Here every wait is a yield, so the caller keeps running.

    Yields None while scanning; the final value is the result list, so a driver can
    read the outcome off the last yield. Each result is
    {'mac', 'rssi', 'name', 'adv'} — `adv` is the raw advertising payload, which is
    what novableid needs to say what the device actually is (scan() throws it away).
    """
    try:
        import novastealth
        if novastealth.blocked():
            yield []
            return
    except Exception:
        pass
    import utime
    found = {}
    cap = MAX_RESULTS

    def _irq(event, data):
        # This runs in a BLE INTERRUPT and fires once per advertisement — many
        # times a second in any populated area. It used to build a dict, two
        # bytes objects and a formatted MAC string every time, forever. Those are
        # small, short-lived allocations scattered through a heap that never
        # compacts, and they are what left the device with 36 KB free in ~1 KB
        # scraps: enough memory, none of it usable.
        #
        # It now stores a plain tuple and does no formatting at all; the strings
        # are built once per scan, below, for the handful of devices we keep.
        if event == _IRQ_SCAN_RESULT:
            _at, addr, _t, rssi, adv = data
            prev = found.get(addr)
            if prev is not None:
                if rssi <= prev[0]:
                    return
            elif len(found) >= cap:
                return                      # bounded: a crowded room cannot
            found[bytes(addr)] = (rssi, bytes(adv))

    try:
        ble = _radio()
    except Exception:
        yield []
        return
    try:
        ble.irq(_irq)
        ble.gap_scan(ms, 30000, 30000, True)     # active scan -> get names
        t0 = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), t0) < ms:
            # Re-check EVERY step, not just at the start. A 3-second scan that
            # only checked once would keep the receiver running for the rest of
            # its window after incognito was engaged mid-scan.
            try:
                import novastealth
                if novastealth.blocked():
                    break
            except Exception:
                pass
            yield None
    except Exception:
        pass
    finally:
        try:
            ble.gap_scan(None)
        except Exception:
            pass
    # Format outside the interrupt, once, for what we actually kept.
    out = []
    for mac, (rssi, payload) in found.items():
        out.append({
            'mac': ':'.join('{:02x}'.format(b) for b in mac),
            'rssi': rssi,
            'name': _adv_name(payload) or '',
            'adv': payload,
        })
    found.clear()
    out.sort(key=lambda d: d['rssi'], reverse=True)
    yield out


def _rand(n):
    try:
        import uos
        return uos.urandom(n)
    except Exception:
        import utime
        seed = utime.ticks_us()
        return bytes((seed >> (i % 24)) & 0xff for i in range(n))


def _proximity_packet(model_bytes):
    """Apple Continuity proximity-pairing advertisement (31 bytes):
    1E FF 4C 00 07 19 07 <model 2B> 55 <battery/case/lid/color/pad> + 16 random."""
    head = bytes([0x1E, 0xFF, 0x4C, 0x00, 0x07, 0x19, 0x07]) + model_bytes \
        + bytes([0x55, 0x00, 0x00, 0x00, 0x00, 0x00])
    return head + _rand(16)                       # 7 + 2 + 6 + 16 = 31 bytes


def _fastpair_packet(model3):
    """Google Fast Pair advertisement -> Android pairing popup. Flags AD + service
    data for UUID 0xFE2C (Fast Pair) carrying a 3-byte model id, + a tx-power AD."""
    return bytes([0x02, 0x01, 0x06,                       # flags
                  0x06, 0x16, 0x2C, 0xFE]) + model3 \
        + bytes([0x02, 0x0A, 0x00])                       # tx power


def advertise_raw(data, interval_ms=40):
    """Start advertising raw AD bytes. Call stop() to end (or use the bounded
    proximity_ping). Non-connectable broadcast."""
    ble = _radio()
    ble.gap_advertise(int(interval_ms * 1000), adv_data=bytes(data), connectable=False)


def stop():
    global _ble
    try:
        if _ble is not None:
            _ble.gap_advertise(None)
    except Exception:
        pass


def _packet_for(platform, model):
    if platform == 'android':
        return _fastpair_packet(MODELS_ANDROID.get(model, MODELS_ANDROID['headphones']))
    return _proximity_packet(MODELS.get(model, MODELS['airpods']))


def ping(platform='apple', model=None, secs=10, cancel=None):
    """Broadcast a 'device nearby' pairing advertisement for `secs` seconds so a
    nearby phone shows the pairing card — Apple (iOS) or Android (Fast Pair). This
    is the same effect a Flipper BLE 'ping' has, so cross-tool scripts port over.
    BOUNDED on purpose — point it at YOUR phone (own-device / authorized use).
    Returns the model used, or None if BLE is unavailable. `cancel()` stops early."""
    # Incognito latch: refuse while stealth is engaged. Killing the radio isn't
    # enough by itself — this call would just re-activate it.
    try:
        import novastealth
        if novastealth.blocked():
            return False
    except Exception:
        pass
    if not available():
        return None
    import utime
    cancel = cancel or (lambda: False)
    if model is None:
        model = 'headphones' if platform == 'android' else 'airpods'
    advertise_raw(_packet_for(platform, model), interval_ms=20)
    t0 = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), t0) < int(secs * 1000):
        if cancel():
            break
        utime.sleep_ms(120)
        try:
            advertise_raw(_packet_for(platform, model), interval_ms=20)
        except Exception:
            break
    stop()
    return model


def start_ping(platform='apple', model=None):
    """Start advertising a pairing packet and RETURN immediately (non-blocking) —
    the BLE radio keeps broadcasting on its own. Call stop() to end. For the GUI,
    which can't block the event loop. Returns the model used, or None."""
    # Incognito latch: refuse while stealth is engaged. Killing the radio isn't
    # enough by itself — this call would just re-activate it.
    try:
        import novastealth
        if novastealth.blocked():
            return False
    except Exception:
        pass
    if not available():
        return None
    if model is None:
        model = 'headphones' if platform == 'android' else 'airpods'
    advertise_raw(_packet_for(platform, model), interval_ms=20)
    return model


# Back-compat alias.
def proximity_ping(model='airpods', secs=10):
    return ping('apple', model, secs)
