# Flipper .rfid (125 kHz LF) format: parse / build round-trip + validation.
import sys
import _shims
_shims.install()
from _shims import T
import novarfid as R

t = T('test_novarfid')

EM = ("Filetype: Flipper RFID key\nVersion: 1\n# an EM4100 fob\n"
      "Key type: EM4100\nData: 1A 2B 3C 4D 5E\n")
c = R.parse(EM)
t.ok(c is not None, 'parses a Flipper RFID key')
t.eq(c['key_type'], 'EM4100', 'key type')
t.eq(R.hexs(c['data']), '1A 2B 3C 4D 5E', 'data bytes')
t.ok(R.build('EM4100', c['data']) == ("Filetype: Flipper RFID key\nVersion: 1\n"
     "Key type: EM4100\nData: 1A 2B 3C 4D 5E\n"), 'build round-trip (no comment)')

t.ok(R.valid(c), 'EM4100 length (5) valid')
t.ok(not R.valid({'key_type': 'EM4100', 'data': b'\x01\x02'}), 'wrong EM4100 length invalid')
t.ok(R.valid({'key_type': 'MysteryProto', 'data': b'\x01'}), 'unknown type -> not length-checked')
t.eq(R.data_len('H10301'), 3, 'HID H10301 length')
t.eq(R.data_len('FDX-B'), 8, 'FDX-B length')

t.ok(R.parse('Filetype: Something Else\nData: 01\n') is None, 'non-RFID file -> None')
t.ok(R.parse('Filetype: Flipper RFID key\nKey type: EM4100\n') is None, 'no Data -> None')

sys.exit(t.done())
