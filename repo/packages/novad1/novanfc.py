# Desc: Nova D1 NFC — Flipper Zero .nfc (v4) file format read/write.
# File: /Packages/NovaD1/novanfc.py
#
# The interop layer: Nova reads and writes the EXACT .nfc files a Flipper Zero
# uses, so dumps move both ways between the two tools. Grounded on the official
# spec (developer.flipper.net .../nfc_file_format.html, Version 4).
#
# Design: a .nfc file is parsed into an ORDERED list of records — ('kv', key,
# value) for "Key: value" lines and ('raw', text) for comments/blanks — so write()
# re-emits it BYTE-FOR-BYTE (the round-trip interop proof). Accessors + builders
# sit on top for the scanner/cloner. Hex is UPPERCASE space-separated, as Flipper
# writes it; unknown bytes are "??" (kept verbatim).
#
# ATQA byte order: Flipper stores it big-endian as printed (NTAG = "00 44", Classic
# 4K = "00 02"). The PN532 returns SENS_RES little-endian on the wire, so the READ
# layer must swap before handing ATQA here — decided/verified against a real dump on
# hardware, not assumed silently (see DEVICE notes).
#
# MicroPython-safe: no f-strings, positional split, .format() only.

FILETYPE = 'Flipper NFC device'
VERSION = '4'

DT_ISO3A = 'ISO14443-3A'
DT_ULTRALIGHT = 'NTAG/Ultralight'
DT_CLASSIC = 'Mifare Classic'


def hexs(bs, sep=' '):
    """Bytes -> 'AA BB CC' (uppercase, Flipper style)."""
    return sep.join('{:02X}'.format(b & 0xff) for b in bs)


def unhex(s):
    """'AA BB CC' (or 'AABBCC' / with ':') -> bytes. '??' bytes become 0x00 (use
    the string accessors if you must preserve unknown markers verbatim)."""
    s = s.replace(' ', '').replace(':', '')
    out = bytearray()
    for i in range(0, len(s) - 1, 2):
        pair = s[i:i + 2]
        out.append(0 if '?' in pair else int(pair, 16))
    return bytes(out)


class NfcCard:
    """An ordered, round-trip-faithful view of a .nfc file."""

    def __init__(self, records=None):
        self.records = records if records is not None else []

    # -- key/value access (first match) --
    def get(self, key, default=None):
        for r in self.records:
            if r[0] == 'kv' and r[1] == key:
                return r[2]
        return default

    def set(self, key, value):
        for i, r in enumerate(self.records):
            if r[0] == 'kv' and r[1] == key:
                self.records[i] = ('kv', key, value)
                return
        self.records.append(('kv', key, value))

    # -- typed conveniences --
    def device_type(self):
        return self.get('Device type', '')

    def uid(self):
        u = self.get('UID')
        return unhex(u) if u else b''

    def atqa(self):
        a = self.get('ATQA')
        return unhex(a) if a else b''

    def sak(self):
        s = self.get('SAK')
        return unhex(s)[0] if s else 0

    def memory(self):
        """Ordered list of (label, value_str) for Page N / Block N lines."""
        out = []
        for r in self.records:
            if r[0] == 'kv' and (r[1].startswith('Page ') or r[1].startswith('Block ')):
                out.append((r[1], r[2]))
        return out

    def to_text(self):
        lines = []
        for r in self.records:
            if r[0] == 'kv':
                lines.append(r[1] + ': ' + r[2])
            else:
                lines.append(r[1])
        return '\n'.join(lines) + '\n'


def parse(text):
    """Parse .nfc text into an NfcCard, preserving order, comments and blanks so
    to_text() reproduces it byte-for-byte."""
    records = []
    raw = text.split('\n')
    # A trailing '' from a final newline is dropped (to_text re-adds the newline).
    if raw and raw[-1] == '':
        raw = raw[:-1]
    for line in raw:
        st = line.strip()
        if not st or st[0] == '#':
            records.append(('raw', line))
            continue
        idx = line.find(':')
        if idx < 0:
            records.append(('raw', line))
            continue
        key = line[:idx].strip()
        value = line[idx + 1:].strip()
        records.append(('kv', key, value))
    return NfcCard(records)


def _header(device_type, uid, atqa, sak):
    return [
        ('kv', 'Filetype', FILETYPE),
        ('kv', 'Version', VERSION),
        ('kv', 'Device type', device_type),
        ('kv', 'UID', hexs(uid)),
        ('kv', 'ATQA', hexs(atqa)),
        ('kv', 'SAK', hexs([sak])),
    ]


def build_iso14443a(uid, atqa, sak):
    """UID-only / unsupported-but-identified card."""
    return NfcCard(_header(DT_ISO3A, uid, atqa, sak))


def build_ultralight(uid, atqa, sak, ul_type, pages, signature=None,
                     mifare_version=None, counters=None, tearing=None,
                     pages_read=None):
    """pages: list of 4-byte values (bytes or 'AA BB CC DD' strings, '??' ok).
    Field ORDER matches the Flipper spec for NTAG/Ultralight exactly."""
    recs = _header(DT_ULTRALIGHT, uid, atqa, sak)
    recs.append(('kv', 'Data format version', '2'))
    recs.append(('kv', 'NTAG/Ultralight type', ul_type))
    recs.append(('kv', 'Signature', hexs(signature) if signature is not None else hexs(b'\x00' * 32)))
    if mifare_version is None:
        mifare_version = b'\x00\x04\x04\x02\x01\x00\x11\x03'
    recs.append(('kv', 'Mifare version', hexs(mifare_version)))
    counters = counters if counters is not None else [0, 0, 0]
    tearing = tearing if tearing is not None else [0, 0, 0]
    for i in range(3):
        recs.append(('kv', 'Counter ' + str(i), str(counters[i])))
        recs.append(('kv', 'Tearing ' + str(i), '{:02X}'.format(tearing[i] & 0xff)))
    total = len(pages)
    recs.append(('kv', 'Pages total', str(total)))
    recs.append(('kv', 'Pages read', str(pages_read if pages_read is not None else total)))
    for i, p in enumerate(pages):
        recs.append(('kv', 'Page ' + str(i), p if isinstance(p, str) else hexs(p)))
    recs.append(('kv', 'Failed authentication attempts', '0'))
    return NfcCard(recs)


def build_classic(uid, atqa, sak, mc_type, blocks):
    """blocks: list of 16-byte values (bytes or hex strings, '??' ok). Field ORDER
    matches the Flipper spec for Mifare Classic (type before data-format-version)."""
    recs = _header(DT_CLASSIC, uid, atqa, sak)
    recs.append(('kv', 'Mifare Classic type', mc_type))
    recs.append(('kv', 'Data format version', '2'))
    for i, b in enumerate(blocks):
        recs.append(('kv', 'Block ' + str(i), b if isinstance(b, str) else hexs(b)))
    return NfcCard(recs)


# --- identification from the anticollision result -----------------------------
# pages/blocks counts per chip, for naming + a default-allocation when reading.
_NTAG_BY_PAGES = {45: 'NTAG213', 135: 'NTAG215', 231: 'NTAG216',
                  20: 'Mifare Ultralight 11', 41: 'Mifare Ultralight 21',
                  16: 'Mifare Ultralight'}
_CLASSIC_BY_SAK = {0x08: ('1K', 64), 0x18: ('4K', 256),
                   0x09: ('Mini', 20), 0x88: ('1K', 64), 0x98: ('4K', 256)}


def identify(sak, atqa, mem_pages=None):
    """Best-effort card classification from SAK/ATQA (+ optional page count).
    Returns (device_type, sub_type_or_None). Conservative: anything unrecognised
    is ISO14443-3A (we still capture UID/ATQA/SAK)."""
    a = 0
    if atqa:
        a = (atqa[0] << 8) | (atqa[1] if len(atqa) > 1 else 0)
    if sak in _CLASSIC_BY_SAK:
        return DT_CLASSIC, _CLASSIC_BY_SAK[sak][0]
    if sak == 0x00 and (a & 0x00ff) == 0x44:        # Ultralight/NTAG family
        sub = _NTAG_BY_PAGES.get(mem_pages or 0, 'NTAG215')
        return DT_ULTRALIGHT, sub
    return DT_ISO3A, None


def classic_block_count(mc_type):
    return 256 if '4' in mc_type else (20 if 'ini' in mc_type else 64)
