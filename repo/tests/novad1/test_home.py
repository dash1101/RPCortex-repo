# Home/app-system: folders home, categories, and installed script-apps auto-landing
# on the home in their auto-derived category.
import sys
import _shims
_shims.install()
from _shims import T
import novagui
import novastore

t = T('test_home')

# Stub the scripts store with two installed button-grid apps of different kinds.
_store = {
    'ble-pranks.txt': 'title: BLE Pranks\nAirPods = ble ping apple airpods\nAndroid = ble ping android\n',
    'systools.txt': 'title: Sys Tools\nInfo = run sysinfo\nUptime = run uptime\n',
}
novastore.list_codes = lambda cat: list(_store) if cat == 'scripts' else []
novastore.read_code = lambda cat, n: _store.get(n)

apps = novagui._all_apps()
skeys = [a[0] for a in apps if a[0].startswith('script_')]
t.eq(len(skeys), 2, 'both installed script-apps appear on the home')
t.eq(novagui._app_category('script_ble-pranks.txt'), 'Wireless', 'ble app auto-cat Wireless')
t.eq(novagui._app_category('script_systools.txt'), 'System', 'run app auto-cat System')

# built-in categories still correct
t.eq(novagui._app_category('pn532'), 'Wireless', 'NFC -> Wireless')
t.eq(novagui._app_category('gps'), 'Sensors', 'GPS -> Sensors')
t.eq(novagui._app_category('diag'), 'System', 'Diagnostics -> System')
t.eq(novagui._app_category('unknownkey'), 'Tools', 'unknown -> Tools default')

# folders home groups everything; script-apps land in their folders
home = novagui.build_home({})
folders = {it[1].split(' (')[0]: it for it in home.items}
t.ok('Wireless' in folders and 'System' in folders, 'category folders built')
wireless = [it[1] for it in folders['Wireless'][2]().items]
system = [it[1] for it in folders['System'][2]().items]
t.ok('BLE Pranks' in wireless, 'ble script-app in Wireless folder')
t.ok('Sys Tools' in system, 'run script-app in System folder')

# a home config must NOT hide installed script-apps
_shims.set_reg({'Apps.NovaD1_Home': 'gps'})     # user pinned only GPS
home2 = novagui.build_home({})
allnames = []
for it in home2.items:
    allnames += [x[1] for x in it[2]().items]
t.ok('BLE Pranks' in allnames, 'script-apps show even with a restrictive home config')
_shims.set_reg({})

# Diagnostics app absorbs the pure test modules (they are NOT top-level apps)
keys = [a[0] for a in apps]
t.ok('diag' in keys, 'Diagnostics app present')
for probe in novagui._DIAG_ONLY:
    t.ok(probe not in keys, '{} folded into Diagnostics (not a home app)'.format(probe))

# --- App Manager v2: reorder (grab + move) + enable/disable, both persisting ---
import novainput as ev
saved = {}
_shims.set_reg({})
sys.modules['regedit'].save = lambda k, v: saved.__setitem__(k, v) or True
m = novagui.ManageAppsScreen([('a', 'Alpha'), ('b', 'Beta'), ('c', 'Gamma'), ('d', 'Delta')],
                             ['a', 'b', 'c', 'd'])
m.on_event(ev.HOME)                       # grab Alpha
m.on_event(ev.ROT_CW)
m.on_event(ev.ROT_CW)                     # move it down twice
t.eq(m._order, ['b', 'c', 'a', 'd'], 'reorder moves the grabbed item')
t.eq(saved.get('Apps.NovaD1_Home'), 'b,c,a,d', 'reorder persists to Apps.NovaD1_Home')
m.on_event(ev.HOME)                       # drop
t.ok(not m._moving, 'Home drops the item')
m.sel = 0
m.on_event(ev.SELECT)                     # disable 'b'
t.ok('b' not in saved['Apps.NovaD1_Home'].split(','), 'disable removes from saved set')

sys.exit(t.done())
