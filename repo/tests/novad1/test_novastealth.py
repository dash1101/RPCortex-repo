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

_shims.set_reg({})
t.ok(st.maybe_randomize_mac() is None, 'MAC randomisation is off by default')
t.ok(calls['mac_set'] is None, 'and nothing was written to the interface')
_shims.set_reg({'Apps.NovaD1_RandomMAC': 'on'})
res = st.maybe_randomize_mac()
t.ok(res is not None and ':' in res, 'when enabled, a MAC string is returned')
t.ok(calls['mac_set'] is not None and len(calls['mac_set']) == 6,
     'and a 6-byte MAC was written to the WiFi interface')

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

sys.exit(t.done())
