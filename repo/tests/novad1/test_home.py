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

# --- Category reassignment: override layer, persistence, folder placement ---
reg = {}
sys.modules['regedit'].read = lambda k: reg.get(k)
sys.modules['regedit'].save = lambda k, v: reg.__setitem__(k, v) or True
novagui._load_cat_overrides()
t.eq(novagui._app_category('gps'), 'Sensors', 'gps default folder is Sensors')
novagui._set_cat_override('gps', 'Tools')
t.eq(novagui._app_category('gps'), 'Tools', 'override moves gps to Tools')
t.ok('gps:Tools' in reg.get('Apps.NovaD1_AppCats', ''), 'override persisted to the registry')
novagui._CAT_OVERRIDE.clear()
novagui._load_cat_overrides()             # reload from disk
t.eq(novagui._app_category('gps'), 'Tools', 'override survives a reload')
home3 = novagui.build_home({})
fol = {it[1].split(' (')[0]: it for it in home3.items}
t.ok('gps' in [x[0] for x in fol['Tools'][2]().items], 'reassigned app is in the Tools folder')
novagui._set_cat_override('gps', None)     # 'auto' clears it
t.eq(novagui._app_category('gps'), 'Sensors', 'clearing the override restores the default')

# manager: grab an app, SELECT cycles its folder (and persists)
reg.clear()
novagui._CAT_OVERRIDE.clear()
m2 = novagui.ManageAppsScreen([('pn532', 'NFC'), ('gps', 'GPS')], ['pn532', 'gps'])
m2.sel = 1                                 # GPS
m2.on_event(ev.HOME)                       # grab -> edit mode
m2.on_event(ev.SELECT)                     # cycle folder
t.ok(novagui._app_category('gps') != 'Sensors', 'SELECT-while-grabbed changes the folder')
t.ok('gps:' in reg.get('Apps.NovaD1_AppCats', ''), 'manager folder change persists')

# shell path: novad1 apps cat <key> <folder>
import novad1 as ND
reg.clear(); novagui._CAT_OVERRIDE.clear()
def _sink(*a, **k):
    pass
ND._apps(_sink, _sink, _sink, _sink, _sink, 'cat pn532 Tools')
t.ok('pn532:Tools' in reg.get('Apps.NovaD1_AppCats', ''), 'shell apps cat sets an override')
ND._apps(_sink, _sink, _sink, _sink, _sink, 'cat pn532 auto')
t.ok('pn532' not in reg.get('Apps.NovaD1_AppCats', ''), 'shell apps cat auto clears it')

# --- Clock app: view toggle, stopwatch start/stop/reset, and it renders ---
class _FakeC:
    w = 128
    h = 64
    def text(self, *a, **k):
        pass
    def hline(self, *a, **k):
        pass
    def fill_rect(self, *a, **k):
        pass
    def rect(self, *a, **k):
        pass

ck = novagui.ClockScreen()
t.eq(ck.view, 0, 'clock starts in clock view')
ck.draw(_FakeC())                          # clock view renders without error
ck.on_event(ev.ROT_CW)
t.eq(ck.view, 1, 'turn switches to stopwatch')
ck.on_event(ev.SELECT)                     # start
t.ok(ck.sw_run, 'SELECT starts the stopwatch')
ck.tick(1000); ck.tick(500)
t.eq(ck.sw_ms, 1500, 'stopwatch accumulates while running')
ck.draw(_FakeC())                          # stopwatch view renders
ck.on_event(ev.SELECT)                     # stop
t.ok(not ck.sw_run, 'SELECT stops the stopwatch')
ck.tick(1000)
t.eq(ck.sw_ms, 1500, 'a stopped stopwatch does not accumulate')
ck.on_event(ev.SELECT)                     # reset
t.eq(ck.sw_ms, 0, 'SELECT resets a stopped stopwatch')
t.eq(ck.on_event(ev.BACK), ev.BACK, 'BACK exits the clock')
t.eq(novagui._app_category('clock'), 'Tools', 'clock is a Tools app')

sys.exit(t.done())
