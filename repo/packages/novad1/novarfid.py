# Desc: Nova D1 LF RFID — Flipper Zero .rfid (125 kHz) file format read/write.
# File: /Packages/NovaD1/novarfid.py
#
# The .rfid interop layer, matching the .nfc/.sub/.ir set. A Flipper .rfid file is
# tiny — a key type + the raw data bytes:
#     Filetype: Flipper RFID key
#     Version: 1
#     Key type: EM4100
#     Data: 1A 2B 3C 4D 5E
# This parses/writes that exactly, so LF fobs move both ways between Nova and a
# Flipper. NOTE: Nova has no 125 kHz LF hardware yet (the PN532 is 13.56 MHz HF
# only) — this is the FORMAT + validation, ready for an LF reader (RDM6300 / EM4095
# read, T5577 write). The format work is fully testable now; on-air read/write/
# emulate is a future hardware addition (see the roadmap Cat 6).
#
# MicroPython-safe: no f-strings, positional split, .format() only.

FILETYPE = 'Flipper RFID key'
VERSION = '1'

# Key type -> expected data length in bytes (for validation / a sensible default
# capture length). Types Nova doesn't know still parse — length just isn't checked.
KEY_TYPES = {
    'EM4100': 5, 'H10301': 3, 'Indala26': 3, 'IoProxXSF': 4,
    'FDX-A': 5, 'FDX-B': 8, 'Viking': 4, 'Jablotron': 5,
    'PAC/Stanley': 4, 'Paradox': 6, 'Keri': 4, 'Gallagher': 8,
    'Nexwatch': 8, 'Securakey': 4, 'AWID': 6, 'Pyramid': 6,
}


def hexs(bs, sep=' '):
    return sep.join('{:02X}'.format(b & 0xff) for b in bs)


def unhex(s):
    s = s.replace(' ', '').replace(':', '')
    out = bytearray()
    for i in range(0, len(s) - 1, 2):
        try:
            out.append(int(s[i:i + 2], 16))
        except ValueError:
            pass
    return bytes(out)


def parse(text):
    """Parse a .rfid file -> {'key_type': str, 'data': bytes}, or None if it isn't a
    Flipper RFID key file / has no data."""
    key_type = None
    data = None
    is_rfid = False
    for line in text.split('\n'):
        line = line.strip()
        if not line or line[0] == '#' or ':' not in line:
            continue
        k, v = line.split(':', 1)
        k = k.strip()
        v = v.strip()
        if k == 'Filetype':
            is_rfid = (v == FILETYPE)
        elif k == 'Key type':
            key_type = v
        elif k == 'Data':
            data = unhex(v)
    if not is_rfid or data is None:
        return None
    return {'key_type': key_type or 'EM4100', 'data': data}


def build(key_type, data):
    """Build a Flipper .rfid file from a key type + data bytes."""
    return ('Filetype: ' + FILETYPE + '\nVersion: ' + VERSION +
            '\nKey type: ' + str(key_type) + '\nData: ' + hexs(data) + '\n')


def data_len(key_type):
    """Expected data length (bytes) for a key type, or None if unknown."""
    return KEY_TYPES.get(key_type)


def valid(card):
    """True if a parsed card's data length matches its (known) key type."""
    if not card:
        return False
    n = KEY_TYPES.get(card.get('key_type'))
    return n is None or len(card.get('data', b'')) == n
