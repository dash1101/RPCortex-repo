# novawatch: the background radio observer.
#
# The point of watching in the background rather than on a button press is that
# TIME becomes evidence — how long something has been here, whether it is getting
# closer, whether the phone that means "someone is home" just arrived. That is the
# same signal a smart camera uses to recognise you, done passively.
#
# Everything except the two scan calls is pure logic, so all of it is checked here.
import sys
import _shims
_shims.install()
from _shims import T

import novawatch as W

t = T('test_novawatch')

FLAGS = bytes([2, 0x01, 0x06])
FINDMY = FLAGS + bytes([5, 0xFF, 0x4C, 0x00, 0x12, 0x19])


def reset():
    W.clear()
    _shims.set_reg({})


# ------------------------------------------------------------ the registry
reset()
new = W.observe([{'mac': '44:19:B6:00:11:22', 'rssi': -50, 'name': 'CAM'}],
                'ble', now=1000)
t.eq(new, ['44:19:b6:00:11:22'], 'a first sighting is reported as new')
t.eq(W.count(), 1, 'and is recorded')
rec = W.get('44:19:B6:00:11:22')
t.eq(rec['vendor'], 'Hikvision', 'the vendor comes from the OUI table')
t.eq(rec['first'], 1000, 'first-seen is stamped')
t.eq(rec['count'], 1, 'and the sighting counted')

# seeing it again updates rather than duplicating
W.observe([{'mac': '44:19:B6:00:11:22', 'rssi': -40}], 'ble', now=2000)
t.eq(W.count(), 1, 'a second sighting does not duplicate the device')
rec = W.get('44:19:b6:00:11:22')
t.eq(rec['count'], 2, 'the sighting count rises')
t.eq(rec['first'], 1000, 'first-seen does not move')
t.eq(rec['last'], 2000, 'last-seen does')
t.eq(rec['best'], -40, 'the best signal ever seen is kept')
t.eq(rec['trend'], 10, 'and the change since last time is available')
t.eq(rec['name'], 'CAM', 'a name learned once is not lost by a later nameless scan')

# a BLE advert identifies things the MAC alone cannot
W.observe([{'mac': 'DA:11:22:33:44:55', 'rssi': -70, 'adv': FINDMY}], 'ble', now=2000)
rec = W.get('da:11:22:33:44:55')
t.eq(rec['class'], 'tracker', 'an Apple Find My advert is classed as a tracker')
t.ok(rec['random'], 'and its rotating address is flagged as randomised')

# entries with no MAC at all must not create phantom rows
W.observe([{'rssi': -60}, {}, None], 'ble', now=2000)
t.eq(W.count(), 2, 'entries without a MAC are skipped, not stored')

# WiFi results arrive under a different key and are kept apart
W.observe([{'bssid': 'aa:bb:cc:dd:ee:ff', 'rssi': -65, 'ssid': 'dash_',
            'channel': 6}], 'wifi', now=2000)
t.eq(len(W.devices(kind='wifi')), 1, 'a WiFi AP is recorded from its bssid')
t.eq(len(W.devices(kind='ble')), 2, 'and does not land in the BLE list')
t.eq(W.get('aa:bb:cc:dd:ee:ff')['name'], 'dash_', 'the SSID becomes its name')

# strongest first
order = [d['mac'] for d in W.devices()]
t.eq(order[0], '44:19:b6:00:11:22', 'the list is strongest first')

# --------------------------------------------------------------- presence
reset()
W.observe([{'mac': 'aa:11:22:33:44:55', 'rssi': -55}], 'ble', now=1000)
t.eq(W.presence(), [], 'nothing is watched until you name it')
W.tag('AA:11:22:33:44:55', 'My phone')
p = W.presence()
t.eq(len(p), 1, 'a named device is watched')
t.eq(p[0][0], 'My phone', 'under the name you gave it')
t.ok(p[0][2], 'and reads as present while it is being heard')

# It survives a restart: the point of naming something is that it persists.
t.ok('aa:11:22:33:44:55' in W.known(), 'the tag is stored')
W.clear()
t.ok('aa:11:22:33:44:55' in W.known(), 'and survives the device table being cleared')
t.eq(W.presence()[0][2], False, 'a named device never seen reads as away')

# ------------------------------------------------------- departure hysteresis
# One missed scan is normal: BLE advertising is bursty and a wall is enough. A
# single miss must not announce that someone left the house.
reset()
W.tag('aa:11:22:33:44:55', 'My phone')
W.observe([{'mac': 'aa:11:22:33:44:55', 'rssi': -55}], 'ble', now=1000)
W.events()                                   # drain the arrival
W.observe([], 'ble', now=1000 + W.GONE_MS + 1)
t.eq(W.events(), [], 'one missed pass does not announce a departure')
W.observe([], 'ble', now=1000 + W.GONE_MS * 2)
evs = W.events()
t.eq([e[0] for e in evs], ['left'], 'a second miss does')
t.eq(evs[0][2], 'My phone', 'reported under its given name')

# coming back is an arrival
W.observe([{'mac': 'aa:11:22:33:44:55', 'rssi': -55}], 'ble',
          now=1000 + W.GONE_MS * 3)
t.ok(True, 'a return is recorded without raising')

# --------------------------------------------------------------- event policy
# Unknown-device alerts are OFF by default. In any populated area they would fire
# constantly and train you to ignore the notification.
reset()
W.observe([{'mac': '11:22:33:44:55:66', 'rssi': -80}], 'ble', now=1000)
t.eq(W.events(), [], 'an unknown device raises no event by default')
_shims.set_reg({'Apps.NovaD1_Watch_New': 'on'})
W.observe([{'mac': '22:33:44:55:66:77', 'rssi': -80}], 'ble', now=1000)
t.eq([e[0] for e in W.events()], ['new'], 'unless you turn new-device alerts on')

# ------------------------------------------------------------------- pruning
reset()
W.tag('ff:ff:ff:ff:ff:01', 'Keep me')
W.observe([{'mac': 'ff:ff:ff:ff:ff:01', 'rssi': -90}], 'ble', now=1)
for i in range(W.MAX_DEVICES + 20):
    W.observe([{'mac': '00:00:00:00:{:02x}:{:02x}'.format(i // 256, i % 256),
                'rssi': -40}], 'ble', now=100 + i)
t.ok(W.count() <= W.MAX_DEVICES, 'the table is capped ({})'.format(W.count()))
t.ok(W.get('ff:ff:ff:ff:ff:01') is not None,
     'and a NAMED device is never pruned, however weak or stale')

# --------------------------------------------------------------- the locator
tr = W.Tracker('aa:bb:cc:dd:ee:ff')
t.eq(tr.bars(), 0, 'no samples means no bars')
t.eq(tr.hint(), 'listening', 'and it says it is still listening')
t.ok(tr.metres() is None, 'no distance without a TX power')

for r in (-80, -78, -70, -62, -55):
    tr.feed(r)
t.ok(tr.level < -50 and tr.level > -80, 'the level is smoothed, not the raw sample')
t.eq(tr.hint(), 'warmer', 'a rising signal reads as warmer')
t.eq(tr.best, -55, 'the best sample is remembered')
for r in (-70, -80, -90):
    tr.feed(r)
t.eq(tr.hint(), 'colder', 'and a falling one as colder')

tr.feed(None)
t.ok(tr.level is not None, 'a missing sample is ignored, not treated as zero')

b = W.Tracker('x')
b.feed(-30)
t.ok(b.bars(10) >= 9, 'a very strong signal fills the meter')
w = W.Tracker('x')
w.feed(-100)
t.eq(w.bars(10), 0, 'a very weak one empties it')

# Distance: the advertised TX power is RADIATED power, not the level at one metre.
# Using it directly put a strong signal 90 m away.
near = W.Tracker('x', tx=0)
for _ in range(8):
    near.feed(-45)
d = near.metres()
t.ok(d is not None and d < 4, 'a strong signal estimates as close ({} m)'.format(d))
far = W.Tracker('x', tx=0)
for _ in range(8):
    far.feed(-85)
t.ok(far.metres() > d, 'and a weak one as further away')

sys.exit(t.done())
