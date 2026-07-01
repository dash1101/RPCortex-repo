# PN532: anticollision parse, InDataExchange payload, Classic sector math, and the
# NTAG + Mifare Classic dump GENERATORS (against a mock PN532 over I2C).
import sys
import _shims
_shims.install()
from _shims import T
import novamods as M
import novanfc as N

t = T('test_novamods')

# --- Mifare Classic sector math ---
t.eq(M._mc_type(0x08), (64, '1K'), 'SAK 08 -> 1K')
t.eq(M._mc_type(0x18), (256, '4K'), 'SAK 18 -> 4K')
t.eq(M._mc_type(0x09), (20, 'Mini'), 'SAK 09 -> Mini')
t.eq((M._mc_nsectors(64), M._mc_nsectors(256)), (16, 40), 'sector counts 1K/4K')
t.eq((M._mc_sector_first(31), M._mc_sector_first(32), M._mc_sector_first(39)), (124, 128, 240), '4K sector offsets')
t.eq((M._mc_sector_nblocks(31), M._mc_sector_nblocks(32)), (4, 16), '4K sector block counts')

# --- anticollision + InDataExchange parsers ---
sel = bytes([0xD5, 0x4B, 0x01, 0x01, 0x00, 0x44, 0x00, 7]) + bytes.fromhex('04859054129823')
card = M._pn532_card(sel + bytes(4))
t.ok(card and N.hexs(card['uid']) == '04 85 90 54 12 98 23' and card['sak'] == 0x00, '_pn532_card parse')
t.eq(card['atqa'], bytes([0x00, 0x44]), '_pn532_card atqa (as PN532 reports)')
t.eq(M._dataex_payload(bytes([0xD5, 0x41, 0x00]) + bytes(range(16))), bytes(range(16)), 'dataex ok payload')
t.ok(M._dataex_payload(bytes([0xD5, 0x41, 0x14, 0xAA])) is None, 'dataex non-zero status -> None')


class MockPN532:
    """Enough of a PN532 to drive the dump generators. auth toggles Classic keys."""
    def __init__(self, sak=0x00, auth=True):
        self.sak = sak
        self.auth = auth
        self.uid = bytes.fromhex('04859054129823') if sak == 0x00 else bytes.fromhex('A1B2C3D4')

    def scan(self):
        return [0x24]

    def writeto(self, a, b):
        self._last = bytes(b)

    def readfrom(self, a, n):
        b = self._last
        if n == 7:
            return bytes([0, 0, 0xFF, 0, 0xFF, 0, 0])            # ACK
        if b[5:7] == bytes([0xD4, 0x4A]):                        # InListPassiveTarget
            body = bytes([0xD5, 0x4B, 0x01, 0x01, 0x00, (0x44 if self.sak == 0 else 0x00),
                          self.sak, len(self.uid)]) + self.uid
            return body + bytes(max(0, 25 - len(body)))
        if b[5:8] == bytes([0xD4, 0x40, 0x01]):                 # InDataExchange
            cmd = b[8]
            if cmd == 0x60 and self.sak == 0x00:                # NTAG GET_VERSION
                return bytes([0xD5, 0x41, 0x00, 0x00, 0x04, 0x04, 0x02, 0x01, 0x00, 0x11, 0x03]) + bytes(19)
            if cmd == 0x3C:                                     # READ_SIG
                return bytes([0xD5, 0x41, 0x00]) + bytes(range(32)) + bytes(13)
            if cmd in (0x60, 0x61):                             # Classic auth
                return (bytes([0xD5, 0x41, 0x00]) if self.auth else bytes([0xD5, 0x41, 0x14])) + bytes(17)
            if cmd == 0x30:                                     # READ block/pages
                blk = b[9]
                if self.sak == 0x00:
                    payload = bytes(((blk + k) & 0xff) for k in range(4) for _ in range(4))
                else:
                    payload = bytes([blk & 0xff] * 16)
                return bytes([0xD5, 0x41, 0x00]) + payload + bytes(30 - 3 - 16)
        return bytes(n)


def drive(gen):
    card = None
    prog = 0
    for ev in gen:
        if ev[0] == 'progress':
            prog += 1
        elif ev[0] == 'done':
            card = ev[1]
    return card, prog


M._pn532_ready = lambda i2c, c, tries=40: True

# NTAG dump (generator)
M._i2c = lambda: MockPN532(0x00, True)
card, prog = drive(M.pn532_dump_ntag())
t.ok(card and card['ntag_type'] == 'NTAG215' and len(card['pages']) == 135, 'NTAG215 full dump')
t.ok(prog > 1, 'NTAG dump is cooperative (many progress yields)')
doc = N.build_ultralight(card['uid'], card['atqa'], card['sak'], card['ntag_type'], card['pages'],
                         signature=card['signature'], mifare_version=card['mifare_version'])
t.ok(N.parse(doc.to_text()).to_text() == doc.to_text(), 'NTAG dump -> valid round-tripping .nfc')

# Classic dump (generator) — keys OK
M._i2c = lambda: MockPN532(0x08, True)
card, prog = drive(M.pn532_dump_classic())
t.ok(card and card['mc_type'] == '1K' and len(card['blocks']) == 64, 'Classic 1K full dump')
t.ok(all(isinstance(b, (bytes, bytearray)) for b in card['blocks']), 'all blocks read with default key')

# Classic dump — no key -> all '??'
M._i2c = lambda: MockPN532(0x08, False)
card2, _ = drive(M.pn532_dump_classic())
t.ok(all(isinstance(b, str) and '??' in b for b in card2['blocks']), 'no-key sectors saved as ??')

sys.exit(t.done())
