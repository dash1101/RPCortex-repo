# BLE: advertisement packet construction (Apple proximity + Google Fast Pair).
import sys
import _shims
_shims.install()
from _shims import T
import novable as B

t = T('test_novable')

ap = B._proximity_packet(B.MODELS['airpods'])
t.eq(len(ap), 31, 'Apple proximity packet length')
t.eq(ap[:6], bytes([0x1E, 0xFF, 0x4C, 0x00, 0x07, 0x19]), 'Apple manuf-data header')
t.eq(ap[7:9], B.MODELS['airpods'], 'Apple model id at index 7')
t.ok(B._proximity_packet(B.MODELS['airpods'])[15:] != ap[15:], 'random tail differs per packet')

fp = B._fastpair_packet(B.MODELS_ANDROID['headphones'])
t.eq(fp[:5], bytes([0x02, 0x01, 0x06, 0x06, 0x16]), 'Fast Pair flags + service-data')
t.eq(fp[5:7], bytes([0x2C, 0xFE]), 'Fast Pair UUID 0xFE2C')
t.eq(fp[7:10], B.MODELS_ANDROID['headphones'], 'Fast Pair 3-byte model id')

t.eq(B._packet_for('android', 'headphones')[5:7], bytes([0x2C, 0xFE]), 'route android -> fastpair')
t.eq(B._packet_for('apple', 'airpods')[2:4], bytes([0x4C, 0x00]), 'route apple -> continuity')

# no `bluetooth` module in tests -> available() False; ping/start_ping must no-op safely
t.ok(B.available() is False, 'available() False without BLE')
t.ok(B.ping('apple') is None and B.start_ping('android') is None, 'ping no-op without hardware')

sys.exit(t.done())
