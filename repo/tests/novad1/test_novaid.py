# Device identification: novaoui (MAC -> vendor) + novableid (BLE advert -> what it is).
#
# The governing rule for both is that a WRONG label is worse than no label. This is a
# tool whose entire job is telling you what something is, so "unknown" is an honest
# answer and a plausible-sounding guess is not. These assertions are mostly about
# what the modules REFUSE to claim.
import sys
import _shims
_shims.install()
from _shims import T

import novaoui
import novableid as B

t = T('test_novaid')

# --------------------------------------------------------------- the OUI table
# Spot-checks against the IEEE MA-L registry the table was generated from.
t.eq(novaoui.lookup('44:19:B6:00:11:22'), ('Hikvision', 'camera'),
     'a Hikvision prefix resolves to Hikvision')
t.eq(novaoui.lookup('B8:27:EB:00:00:01'), ('Raspberry Pi', 'computer'),
     'a Raspberry Pi prefix resolves')
t.eq(novaoui.lookup('b8:27:eb:00:00:01'), ('Raspberry Pi', 'computer'),
     'lower case works too')
t.eq(novaoui.lookup(b'\xb8\x27\xeb\x00\x00\x01'), ('Raspberry Pi', 'computer'),
     'and raw bytes')

# A randomised MAC has NO manufacturer. Phones rotate their address precisely so
# this cannot be done, and reporting a vendor for one would be inventing it.
for mac in ('02:AA:BB:CC:DD:EE', '06:11:22:33:44:55', 'DA:11:22:33:44:55',
            'FE:00:00:00:00:00'):
    v, k = novaoui.lookup(mac)
    t.ok(v is None and k == 'random',
         '{} is reported as randomised, not attributed'.format(mac))

t.eq(novaoui.lookup('00:00:00:00:00:00')[0], None,
     'an unlisted prefix claims no vendor')
t.eq(novaoui.lookup('zzz')[0], None, 'garbage does not raise')
t.eq(novaoui.lookup('')[0], None, 'nor does an empty string')
t.eq(novaoui.prefix('44:19:B6:00:11:22'), '44:19:B6',
     'the raw prefix is offered when no vendor is known')

# The table must stay a packed string, not become a dict: as a dict this data
# costs ~50 KB of RAM on import, which this device does not have.
t.ok(isinstance(novaoui._T, str), 'the table is one packed string')
t.eq(len(novaoui._T) % 8, 0, 'and is a whole number of 8-char records')
t.ok(len(novaoui.VENDORS) == len(novaoui.CLASSES),
     'every vendor has a class')
# sorted, or the binary search silently misses entries
recs = [novaoui._T[i:i + 6] for i in range(0, len(novaoui._T), 8)]
t.eq(recs, sorted(recs), 'the table is sorted, which the binary search requires')
# and every record is findable
import random
random.seed(1)
for r in random.sample(recs, 40):
    t.ok(novaoui._index(r) is not None, 'record {} is findable'.format(r))

# ------------------------------------------------------- BLE advert structure
flags = bytes([2, 0x01, 0x06])
t.eq(B.structures(flags), [(0x01, b'\x06')], 'a single AD structure parses')
t.eq(B.structures(b''), [], 'an empty payload yields nothing')
t.eq(B.structures(b'\x00'), [], 'zero-length padding ends the walk')

# Truncation is normal on air. What was parsed before the break must survive.
whole = flags + bytes([5, 0xFF, 0x4C, 0x00, 0x12, 0x19])
cut = whole[:-2]
t.ok(len(B.structures(cut)) >= 1,
     'a truncated advert keeps the structures that did parse')
for bad in (b'\xff', b'\x05\x09ab', bytes(range(24)), b'\x03\x03\xed'):
    B.structures(bad)
t.ok(True, 'malformed adverts never raise')

# ------------------------------------------------------------- identification
apple = flags + bytes([6, 0xFF, 0x4C, 0x00, 0x10, 0x05, 0x01])
info = B.identify('AC:BC:32:01:02:03', apple)
t.eq(info['vendor'], 'Apple', 'the SIG company ID identifies Apple')
t.eq(info['company_id'], 0x004C, 'and is reported as the raw ID too')

findmy = flags + bytes([5, 0xFF, 0x4C, 0x00, 0x12, 0x19])
info = B.identify('DA:11:22:33:44:55', findmy)
t.eq(info['kind'], 'tracker', 'an Apple Find My advert is a tracker')
t.ok(info['random'], 'even on a rotating address')
t.eq(info['vendor'], 'Apple',
     'manufacturer data still identifies it when the MAC cannot')

tile = flags + bytes([3, 0x03, 0xED, 0xFE]) + bytes([4, 0xFF, 0x7C, 0x06, 0x01])
t.eq(B.identify('C8:11:22:33:44:55', tile)['kind'], 'tracker',
     'a Tile advert is a tracker')

named = flags + bytes([6, 0x09]) + b'Cam01' + bytes([2, 0x0A, 0xF6])
info = B.identify('44:19:B6:00:11:22', named)
t.eq(info['name'], 'Cam01', 'the complete local name is read')
t.eq(info['tx'], -10, 'the advertised TX power is signed correctly')
t.eq(info['vendor'], 'Hikvision', 'and the MAC still supplies the vendor')

# An unknown company must be reported as a NUMBER, never as a nearest match.
odd = flags + bytes([4, 0xFF, 0x34, 0x12, 0x01])
info = B.identify('00:00:00:00:00:01', odd)
t.eq(info['vendor'], '0x1234', 'an unlisted company ID is shown as its ID')

# a bare advert with nothing in it claims nothing
info = B.identify('00:00:00:00:00:02', b'')
t.ok(info['vendor'] is None and info['kind'] is None, 'an empty advert claims nothing')
t.eq(B.describe(info), 'unknown', 'and describes itself honestly')
t.eq(B.describe(B.identify('02:00:00:00:00:03', b'')), 'random MAC',
     'a randomised MAC says so rather than "unknown"')

t.eq(B.tx_power(b''), None, 'no TX power means None, not a made-up number')
t.eq(B.tx_power(bytes([2, 0x0A, 0x04])), 4, 'a positive TX power reads correctly')

sys.exit(t.done())
