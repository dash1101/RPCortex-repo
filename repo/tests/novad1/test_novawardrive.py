# novawardrive: WiFi survey to a WiGLE CSV. Scan parsing, the CSV format, BSSID dedup,
# and the flash storage guard are pure logic, so they test on the host. (The radio + GPS
# reads are isolated and device-only.)
import sys
import types
import _shims
_shims.install()
from _shims import T
import novawardrive as wd

t = T('test_novawardrive')

# ------------------------------------------------------------- scan parsing
raw = [
    (b'HomeNet', b'\xaa\xbb\xcc\xdd\xee\xff', 6, -45, 3, False),
    ('OpenCafe', b'\x00\x11\x22\x33\x44\x55', 11, -70, 0, False),
    (b'', b'\xde\xad\xbe\xef\x00\x01', 1, -80, 4, True),
]
aps = wd.parse_scan(raw)
t.eq(len(aps), 3, 'parses every scan tuple')
t.eq(aps[0]['bssid'], 'aa:bb:cc:dd:ee:ff', 'bssid bytes -> colon hex')
t.eq(aps[0]['ssid'], 'HomeNet', 'bytes SSID decoded')
t.eq(aps[1]['ssid'], 'OpenCafe', 'str SSID kept')
t.eq(aps[0]['channel'], 6, 'channel carried')
t.eq(aps[0]['rssi'], -45, 'rssi carried')
t.eq(wd.parse_scan(None), [], 'None scan -> empty')

# security mapping
t.eq(wd.sec_str(0), 'OPEN', 'sec 0 = OPEN')
t.eq(wd.sec_str(3), 'WPA2-PSK', 'sec 3 = WPA2-PSK')
t.ok(wd.sec_str(99).startswith('WPA'), 'unknown sec is a safe default')

# ------------------------------------------------------------- WiGLE CSV
hdr = wd.wigle_header()
t.ok(hdr.startswith('WigleWifi-1.4'), 'header is WiGLE 1.4')
t.ok('MAC,SSID,AuthMode' in hdr, 'column header present')
t.eq(hdr.count('\n'), 2, 'header is two lines')

row = wd.wigle_row(aps[0], '2026-07-31 22:00:00', 37.123456, -122.654321, 12)
f = row.rstrip('\n').split(',')
t.eq(f[0], 'aa:bb:cc:dd:ee:ff', 'row MAC')
t.eq(f[2], '[WPA2-PSK]', 'row auth in brackets')
t.eq(f[6], '37.123456', 'latitude, 6 dp')
t.eq(f[7], '-122.654321', 'longitude, 6 dp')
t.eq(f[10], 'WIFI', 'row type')

# no-fix row leaves lat/lon blank (still logs the AP)
row2 = wd.wigle_row(aps[1], '2026-07-31 22:00:01')
f2 = row2.rstrip('\n').split(',')
t.eq(f2[6], '', 'no fix -> blank latitude')
t.eq(f2[7], '', 'no fix -> blank longitude')

# an SSID with a comma must be quoted so the CSV stays valid
comma_ap = {'bssid': '01:02:03:04:05:06', 'ssid': 'Cafe, Bar', 'channel': 1,
            'rssi': -60, 'sec': 3}
rc = wd.wigle_row(comma_ap, 'ts')
t.ok('"Cafe, Bar"' in rc, 'comma SSID is quoted')

# ------------------------------------------------------------- dedup session
s = wd.Session()
r1 = s.add(aps, '2026-07-31 22:00:00', 37.1, -122.6)
t.eq(len(r1), 3, 'first pass logs all 3 APs')
t.eq(s.total, 3, 'total = 3 unique')
# second pass: same APs + one new one
raw2 = raw + [('NewAP', b'\x09\x08\x07\x06\x05\x04', 3, -55, 3, False)]
r2 = s.add(wd.parse_scan(raw2), '2026-07-31 22:00:05', 37.1, -122.6)
t.eq(len(r2), 1, 'second pass logs only the NEW AP (dedup by BSSID)')
t.eq(s.total, 4, 'total now 4 unique')
t.eq(s.scans, 2, 'two scan passes counted')

# ------------------------------------------------------- storage guard
# SD writes always allowed
ok_sd, _ = wd.can_write(True)
t.ok(ok_sd, 'SD writes are always allowed')

# flash writes gated on storage_state (stub RPCortex)
rpc = sys.modules.get('RPCortex') or types.ModuleType('RPCortex')
st = {'lvl': 'ok', 'pct': 40}
rpc.storage_state = lambda path='/': (st['pct'], st['lvl'])
sys.modules['RPCortex'] = rpc
st['lvl'] = 'ok'
ok1, _ = wd.can_write(False)
t.ok(ok1, 'flash write ok when storage ok')
st['lvl'] = 'warn'; st['pct'] = 96
ok2, msg2 = wd.can_write(False)
t.ok(ok2 and 'recommend' in msg2.lower(), 'warn level: allowed, recommends SD')
st['lvl'] = 'block'; st['pct'] = 99
ok3, msg3 = wd.can_write(False)
t.ok(not ok3, 'block level: flash write refused')
t.ok('stop' in msg3.lower() or 'full' in msg3.lower(), 'and says why')

sys.exit(t.done())
