# novastealth: the wireless kill switch. Orchestration is pure logic (the hardware
# is behind try/except), so the kill sequence, the stealth flag, MAC randomisation
# and the switch edge all test on the host. The point of the feature is that it can
# NEVER fail to take radios down because one is missing — so the resilience is what
# these assertions guard.
import sys
import types
import _shims
_shims.install()
from _shims import T

t = T('test_novastealth')

# --- stub the on-board radios so WiFi/BLE actually "silence" and are observable ---
calls = {'wifi_active_false': 0, 'wifi_disconnect': 0, 'ble_active_false': 0,
         'mac_set': None}

net = types.ModuleType('network')
net.STA_IF = 0
net.AP_IF = 1


class _WLAN:
    def __init__(s, iface): s.iface = iface
    def isconnected(s): return s.iface == 0
    def disconnect(s): calls['wifi_disconnect'] += 1
    def active(s, v=None):
        if v is False:
            calls['wifi_active_false'] += 1
        return False
    def config(s, **k):
        if 'mac' in k:
            calls['mac_set'] = k['mac']


net.WLAN = _WLAN
sys.modules['network'] = net

bt = types.ModuleType('bluetooth')


class _BLE:
    def active(s, v=None):
        if v is False:
            calls['ble_active_false'] += 1
bt.BLE = _BLE
sys.modules['bluetooth'] = bt

import novastealth as st

# ------------------------------------------------------------------- kill_all
_shims.set_reg({})
down = st.kill_all()
t.ok('WiFi' in down, 'kill_all silences WiFi')
t.ok('BLE' in down, 'kill_all silences BLE')
t.ok(calls['wifi_active_false'] >= 1, 'WiFi interface was deactivated')
t.ok(calls['wifi_disconnect'] >= 1, 'a connected WiFi was disconnected first')
t.ok(calls['ble_active_false'] == 1, 'BLE was deactivated')
t.ok(st.active(), 'the stealth flag is set after kill_all')

# A radio whose kill RAISES must not break the sweep — swap one in.
def _boom():
    raise RuntimeError('radio on fire')
_orig = st._RADIOS
st._RADIOS = (('WiFi', st._kill_wifi), ('Boom', _boom), ('BLE', st._kill_ble))
calls['wifi_active_false'] = 0
down2 = st.kill_all()
t.ok('WiFi' in down2 and 'BLE' in down2, 'a raising radio does not stop the others')
t.ok('Boom' not in down2, 'the failed radio is simply not reported as silenced')
st._RADIOS = _orig

# ------------------------------------------------------------- flag lifecycle
_shims.set_reg({})
t.ok(not st.active(), 'stealth starts off')
st.kill_all()
t.ok(st.active(), 'kill_all engages stealth')
st.restore()
t.ok(not st.active(), 'restore leaves stealth')
t.ok(st.toggle() is True, 'toggle from off -> on returns True')
t.ok(st.active(), 'and stealth is engaged')
t.ok(st.toggle() is False, 'toggle from on -> off returns False')
t.ok(not st.active(), 'and stealth is cleared')

# ------------------------------------------------------ anti-fingerprint MAC
mac = st._random_mac()
t.eq(len(mac), 6, 'a MAC is 6 bytes')
t.ok(mac[0] & 0x02, 'first byte is locally-administered (bit 1 set)')
t.ok(not (mac[0] & 0x01), 'first byte is unicast (bit 0 clear)')
t.ok(st._random_mac() != st._random_mac(), 'two random MACs differ')

# Randomisation is ON by default. The MAC is the one identifier that cannot be
# changed by behaving differently — it goes out in the clear on every association
# — so the device should not be trackable unless you deliberately ask for it.
_shims.set_reg({})
res = st.maybe_randomize_mac()
t.ok(res is not None and ':' in res, 'MAC randomisation is ON by default')
t.ok(calls['mac_set'] is not None and len(calls['mac_set']) == 6,
     'and a 6-byte MAC was written to the WiFi interface')

calls['mac_set'] = None
_shims.set_reg({'Apps.NovaD1_RandomMAC': 'off'})
t.ok(st.maybe_randomize_mac() is None, 'and can be switched off explicitly')
t.ok(calls['mac_set'] is None, 'after which nothing is written to the interface')

# --------------------------------------------------------- physical switch
_shims.set_reg({})
t.ok(st.switch_pin() is None, 'no kill-switch pin by default')
t.ok(not st.poll_edge(), 'poll_edge is inert without a configured pin')
_shims.set_reg({'Apps.NovaD1_PIN_killsw': '5'})
t.eq(st.switch_pin(), 5, 'a configured kill-switch pin resolves')

# machine.Pin in _shims reads value()==0; drive a rising->falling sequence to prove
# the edge logic (press = falling edge). Patch the stubbed Pin.value.
import machine
seq = [1, 1, 0, 0]                      # idle, idle, PRESS, held
i = {'n': 0}
def _val(self, *a):
    v = seq[min(i['n'], len(seq) - 1)]
    i['n'] += 1
    return v
machine.Pin.value = _val
st._sw_last = 1
edges = [st.poll_edge() for _ in range(4)]
t.eq(edges, [False, False, True, False], 'poll_edge fires once on the falling edge')



# --------------------------------------------------- the incognito LATCH
# Killing a radio is not enough on its own: any later scan()/connect() simply
# re-activates the interface, which is why a "killed" WiFi could still be scanned.
# blocked() is the latch every radio entry point must consult.
_shims.set_reg({})
t.ok(not st.blocked(), 'not blocked when stealth is off')
st.kill_all()
t.ok(st.blocked(), 'blocked while stealth is engaged')

import novawardrive as _wd
t.eq(_wd.scan_now(), [], 'WiFi scan refuses while incognito (no re-activation)')

import novable as _ble
t.eq(_ble.scan(100), [], 'BLE scan refuses while incognito')
t.ok(_ble.start_ping('apple') is False, 'BLE advertising refuses while incognito')

st.restore()
t.ok(not st.blocked(), 'latch clears when stealth is left')




# ============================================================ the HARD stop
# Reported: "incognito still isn't a hard stop — I can still scan for wifi and
# connect." The cause was structural. The latch lived only in this package, so
# anything that did not consult it — the OS shell's `wifi scan`, above all — went
# straight past and brought the radio back up. The enforcement now sits in net.py,
# underneath every caller, and this package engages it.
import RPCortex as _R

_shims.set_reg({})
t.ok(not st.blocked(), 'nothing is blocked to start with')
t.ok(not _R.radio_locked(), 'and the OS-level lock is off')

st.kill_all()
t.ok(_R.radio_locked(),
     'engaging incognito engages the OS-WIDE radio lock, not just a local flag')
t.ok(st.blocked(), 'and this package agrees it is blocked')

st.restore()
t.ok(not _R.radio_locked(), 'leaving incognito releases the OS lock')

# The lock must also be honoured when set from the OS side (`radio off`), so the
# two switches are one switch.
_shims.set_reg({})
_R.lock_radios(True)
t.ok(st.blocked(), "`radio off` blocks Nova D1 radios too, without touching incognito")
t.ok(not st.active(), 'and does so without pretending incognito is engaged')
_R.lock_radios(False)

# ------------------------------------------------------- identity randomisation
# A randomised MAC with a fixed hostname is not anonymity: the DHCP hostname goes
# out in the clear and re-links the sessions on its own. Both or neither.
_shims.set_reg({})
names = set(st.random_hostname() for _ in range(20))
t.ok(len(names) > 10, 'hostnames are actually random ({} of 20 unique)'.format(len(names)))
for n in names:
    t.ok(n and len(n) <= 20 and ' ' not in n,
         'hostname {!r} is a usable DHCP name'.format(n))
    break
t.ok(all(not c.isupper() for c in list(names)[0]),
     'and is lower case, like an ordinary host')

import inspect
src = inspect.getsource(st.maybe_randomize_mac)
t.ok('set_hostname' in src,
     'randomising the MAC also randomises the hostname — one without the other '
     'leaves the device just as recognisable')

# ------------------------------------------------------------------ ghost mode
_shims.set_reg({'Apps.NovaD1_Web': 'on', 'Apps.NovaD1_Mesh_Beacon': 'on'})
rows = st.ghost()
closed = dict((n, c) for n, c, _note in rows)
t.ok(closed.get('Radios'), 'ghost silences the radios')
t.ok(closed.get('Web panel'), 'ghost stops serving the web panel')
t.ok(closed.get('LoRa beacon'), 'ghost stops the mesh beacon')
t.ok(closed.get('MAC') and closed.get('Hostname'),
     'ghost leaves a fresh identity armed for when the radios come back')
t.ok('Observer' not in closed,
     'the observer is not listed as a leak — a receiver emits nothing')

# The inventory has to be honest about what is still open.
_shims.set_reg({'Apps.NovaD1_Web': 'on'})
rows = st.leaks()
web = [r for r in rows if r[0] == 'Web panel'][0]
t.ok(not web[1], 'a running web panel is reported as an OPEN channel')
t.ok('network' in web[2].lower(), 'and says why (got {!r})'.format(web[2]))

sys.exit(t.done())
