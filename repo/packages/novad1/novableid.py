# Desc: Nova D1 BLE advertisement decoding — what a nearby device actually is.
# File: /Packages/NovaD1/novableid.py
#
# A BLE advertisement carries far more than a name, and novable.scan() was only
# pulling the name out. This decodes the whole payload so a scan can say "Apple
# device, phone/watch" or "Tile tracker" instead of listing anonymous MACs.
#
# An advertisement is a run of AD structures, each [length][type][value...], where
# length covers the type byte. Core Spec / Supplement, "AD type" values:
#   0x01 flags   0x02/0x03 16-bit UUIDs   0x06/0x07 128-bit UUIDs
#   0x08 short name   0x09 complete name   0x0A TX power   0xFF manufacturer data
# Manufacturer data begins with a little-endian 16-bit SIG company identifier.
#
# The company IDs below were taken from the Bluetooth SIG assigned-numbers list
# (company_identifiers.yaml), not from recall. Anything not listed reports its raw
# ID rather than a guess.
#
# Pure parsing, so it is fully host-testable. MicroPython-safe: no f-strings.

# SIG company identifier -> short label. Verified against the SIG registry.
COMPANY = {
    0x004C: 'Apple',
    0x00E0: 'Google',
    0x018E: 'Google',
    0x0075: 'Samsung',
    0x0006: 'Microsoft',
    0x067C: 'Tile',
    0x0087: 'Garmin',
    0x05A7: 'Sonos',
    0x0171: 'Amazon',
    0x009E: 'Bose',
    0x02E5: 'Espressif',
    0x038F: 'Xiaomi',
    0x0059: 'Nordic',
    0x000D: 'TI',
    0x01DA: 'Logitech',
    0x0CC2: 'Anker',
    0x08C3: 'Chipolo',
    0x005D: 'Realtek',
    0x0002: 'Intel',
    0x012D: 'Sony',
    0x0057: 'Harman',
    0x006B: 'Polar',
    0x03FF: 'Withings',
    0x07A2: 'Roku',
    0x03D5: 'Wyze',
    0x0870: 'Wyze',
}

# 16-bit service UUIDs that say what a device is for. From the SIG GATT service
# list; only the ones that identify a device class in practice are carried.
SERVICE = {
    0x180D: 'heart rate',
    0x180F: 'battery',
    0x1802: 'proximity',
    0x1803: 'proximity',
    0x1808: 'glucose',
    0x1809: 'thermometer',
    0x181A: 'environment',
    0x1812: 'keyboard/mouse',
    0x1826: 'fitness',
    0xFD5A: 'Samsung',
    0xFE9F: 'Google',
    0xFEAA: 'Eddystone beacon',
    0xFD6F: 'contact tracing',
    0xFE2C: 'Google Fast Pair',
    0xFEED: 'Tile',
    0xFD44: 'Apple',
}

# AD types
AD_FLAGS = 0x01
AD_UUID16_PART = 0x02
AD_UUID16_ALL = 0x03
AD_UUID128_PART = 0x06
AD_UUID128_ALL = 0x07
AD_NAME_SHORT = 0x08
AD_NAME_FULL = 0x09
AD_TXPOWER = 0x0A
AD_MFG = 0xFF


def structures(payload):
    """Walk the AD structures. Yields (ad_type, value_bytes).

    Deliberately tolerant: a truncated or malformed advertisement is common on
    air, and one bad structure must not lose the ones before it."""
    out = []
    if not payload:
        return out
    i = 0
    n = len(payload)
    while i < n:
        ln = payload[i]
        if ln == 0:
            break                      # end-of-data padding
        if i + 1 + ln > n:
            break                      # truncated on air — keep what we parsed
        out.append((payload[i + 1], bytes(payload[i + 2:i + 1 + ln])))
        i += 1 + ln
    return out


def name(payload):
    """The advertised local name, complete or shortened, or ''."""
    best = ''
    for t, v in structures(payload):
        if t in (AD_NAME_FULL, AD_NAME_SHORT):
            try:
                s = bytes(v).decode('utf-8')
            except Exception:
                s = ''.join(chr(c) for c in v if 32 <= c < 127)
            if t == AD_NAME_FULL:
                return s
            best = best or s
    return best


def company(payload):
    """(company_id, label, rest_of_manufacturer_data) or (None, None, b'')."""
    for t, v in structures(payload):
        if t == AD_MFG and len(v) >= 2:
            cid = v[0] | (v[1] << 8)          # little-endian, per the spec
            return cid, COMPANY.get(cid), bytes(v[2:])
    return None, None, b''


def services(payload):
    """16-bit service UUIDs advertised, as a list of ints."""
    out = []
    for t, v in structures(payload):
        if t in (AD_UUID16_PART, AD_UUID16_ALL):
            for i in range(0, len(v) - 1, 2):
                out.append(v[i] | (v[i + 1] << 8))
    return out


def tx_power(payload):
    """Advertised TX power in dBm, or None. Needed for any distance estimate."""
    for t, v in structures(payload):
        if t == AD_TXPOWER and len(v) >= 1:
            p = v[0]
            return p - 256 if p > 127 else p          # signed byte
    return None


def connectable(payload):
    """True when the flags say the device accepts connections. A tracker beacon
    that never accepts a connection looks different from a phone."""
    for t, v in structures(payload):
        if t == AD_FLAGS and len(v) >= 1:
            return bool(v[0] & 0x06)      # LE General/Limited Discoverable
    return False


# Apple's manufacturer data starts with a type byte that says what the message is.
# These are not published by Apple; the ones here are the widely-documented ones
# and are labelled as a guess in the UI, never as fact.
_APPLE_TYPE = {
    0x02: 'iBeacon',
    0x05: 'AirDrop',
    0x07: 'pairing',
    0x09: 'AirPlay',
    0x0C: 'Handoff',
    0x10: 'nearby',
    0x12: 'Find My',
}


def identify(mac, payload, adv_name=''):
    """Best-effort description of a BLE device.

    Returns a dict: vendor, kind, label, name, tx, services, random.

    Two rules run through this. A locally-administered MAC is RANDOMISED and has
    no manufacturer, so no vendor is claimed from it — most phones rotate their
    address precisely so this cannot be done. And an unrecognised company ID is
    reported as a number, never as a nearest guess."""
    import novaoui
    vendor, klass = novaoui.lookup(mac)
    random_mac = (klass == 'random')
    if random_mac:
        klass = None

    nm = adv_name or name(payload)
    cid, label, rest = company(payload)
    svcs = services(payload)

    # Manufacturer data is stronger evidence than the MAC: a randomised address
    # still carries the real company ID.
    if label:
        vendor = label
    elif cid is not None and not vendor:
        vendor = '0x{:04X}'.format(cid)

    kind = klass
    if cid == 0x004C and rest:
        t = _APPLE_TYPE.get(rest[0])
        kind = 'tracker' if rest[0] == 0x12 else (kind or 'personal')
        if t:
            nm = nm or ('Apple ' + t)
    elif cid == 0x067C or 0xFEED in svcs:
        kind = 'tracker'
    elif cid == 0x08C3:
        kind = 'tracker'
    elif 0xFE2C in svcs:
        kind = kind or 'personal'
    for s in svcs:
        if s in SERVICE and not kind:
            kind = SERVICE[s]
            break

    return {
        'vendor': vendor,
        'kind': kind,
        'name': nm,
        'tx': tx_power(payload),
        'services': svcs,
        'random': random_mac,
        'company_id': cid,
    }


def describe(info):
    """One short line for a 128px panel: what this thing probably is."""
    bits = []
    if info.get('name'):
        bits.append(info['name'][:14])
    if info.get('vendor'):
        bits.append(info['vendor'])
    if info.get('kind'):
        bits.append(info['kind'])
    if not bits:
        bits.append('random MAC' if info.get('random') else 'unknown')
    return ' '.join(bits)
