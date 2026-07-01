# Flipper .nfc v4 format: round-trip, builders, identify (ATQA order de-risk).
import sys
import _shims
_shims.install()
from _shims import T
import novanfc as N

t = T('test_novanfc')

ISO = ("Filetype: Flipper NFC device\nVersion: 4\nDevice type: ISO14443-3A\n"
       "UID: 34 19 6D 41 14 56 E6\nATQA: 00 44\nSAK: 00\n")
CLASSIC = ("Filetype: Flipper NFC device\nVersion: 4\nDevice type: Mifare Classic\n"
           "UID: BA E2 7C 9D\nATQA: 00 02\nSAK: 18\nMifare Classic type: 4K\n"
           "Data format version: 2\nBlock 0: BA E2 7C 9D B9 18 02 00 46 44 53 37 30 56 30 31\n"
           "Block 1: ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ??\n")
NTAG = ("Filetype: Flipper NFC device\nVersion: 4\n# comment survives\n"
        "Device type: NTAG/Ultralight\nUID: 04 85 90 54 12 98 23\nATQA: 00 44\nSAK: 00\n"
        "Data format version: 2\nNTAG/Ultralight type: NTAG215\nPages total: 2\n"
        "Page 0: 04 85 90 54\nPage 1: 12 98 23 00\n")

for name, txt in [('ISO', ISO), ('Classic', CLASSIC), ('NTAG', NTAG)]:
    t.ok(N.parse(txt).to_text() == txt, 'byte-exact round-trip: ' + name)

c = N.parse(CLASSIC)
t.eq(N.hexs(c.uid()), 'BA E2 7C 9D', 'uid accessor')
t.eq(c.sak(), 0x18, 'sak accessor')
t.eq(len(c.memory()), 2, 'memory() lists Block lines')

# identify — the load-bearing ATQA-order de-risk
t.eq(N.identify(0x00, bytes([0x00, 0x44]), 135), ('NTAG/Ultralight', 'NTAG215'), 'NTAG ATQA 00 44')
t.eq(N.identify(0x00, bytes([0x44, 0x00]), 135), ('NTAG/Ultralight', 'NTAG215'), 'NTAG ATQA reversed')
t.eq(N.identify(0x08, bytes([0x00, 0x04])), ('Mifare Classic', '1K'), 'Classic 1K by SAK')
t.eq(N.identify(0x18, bytes([0x00, 0x02])), ('Mifare Classic', '4K'), 'Classic 4K by SAK')
t.eq(N.identify(0x20, bytes([0x03, 0x44])), ('ISO14443-3A', None), 'DESFire(SAK20) not misrouted')

# builders: field order + self round-trip
nt = N.build_ultralight(bytes.fromhex('04859054129823'), bytes([0, 0x44]), 0, 'NTAG215', [bytes(4)] * 135)
keys = [r[1] for r in nt.records if r[0] == 'kv']
t.ok(keys.index('Data format version') < keys.index('NTAG/Ultralight type'), 'NTAG field order')
t.ok(keys[-1] == 'Failed authentication attempts', 'NTAG ends with failed-auth')
t.eq(nt.get('Pages total'), '135', 'NTAG pages total')
t.ok(N.parse(nt.to_text()).to_text() == nt.to_text(), 'builder self round-trip')

mc = N.build_classic(bytes.fromhex('BAE27C9D'), bytes([0, 2]), 0x18, '4K', [bytes(16)] * 64)
mk = [r[1] for r in mc.records if r[0] == 'kv']
t.ok(mk.index('Mifare Classic type') < mk.index('Data format version'), 'Classic field order')

t.eq(N.hexs(b'\xab\x0c'), 'AB 0C', 'hexs uppercase')
t.eq(N.unhex('AB 0C'), b'\xab\x0c', 'unhex')

sys.exit(t.done())
