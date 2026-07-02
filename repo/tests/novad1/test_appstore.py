# App store: package-format apps (app.cfg + entry) must be valid, and every
# button-grid action must use a known verb. Also tests novaappcfg parse + auto-cat.
import sys
import os
import json
import _shims
_shims.install()
from _shims import T
import nova
import novaappcfg as AC

t = T('test_appstore')

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'novad1-apps')
idx = json.load(open(os.path.join(STORE, 'index.json')))
apps = idx.get('apps', [])
t.ok(len(apps) >= 1, 'index lists at least one app')

VERBS = ('ir', 'subghz', 'lora', 'ble', 'run', 'notify', 'sleep', 'log')
for a in apps:
    name = a.get('name', '?')
    d = a.get('dir')
    t.ok(d and os.path.isdir(os.path.join(STORE, d)), '{}: app dir exists'.format(name))
    cfg_path = os.path.join(STORE, d, 'app.cfg')
    t.ok(os.path.exists(cfg_path), '{}: has app.cfg'.format(name))
    if not os.path.exists(cfg_path):
        continue
    cfg = AC.parse(open(cfg_path).read())
    for f in ('name', 'ver', 'kind', 'entry'):
        t.ok(f in cfg, '{}: app.cfg has {}'.format(name, f))
    entry = os.path.join(STORE, d, cfg.get('entry', ''))
    t.ok(os.path.exists(entry), '{}: entry file exists'.format(name))
    if cfg.get('kind') == 'buttons' and os.path.exists(entry):
        content = open(entry).read()
        title, btns = nova.parse_buttons(content)
        t.ok(len(btns) >= 1, '{}: parses to >=1 button'.format(name))
        bad = [lbl for lbl, act in btns if act.split(None, 1)[0] not in VERBS]
        t.ok(not bad, '{}: all actions known verbs (bad: {})'.format(name, bad))
        cat = AC.category(cfg, content)
        t.ok(cat in AC._CATEGORIES, '{}: resolves to a home category ({})'.format(name, cat))

# --- novaappcfg unit checks ---
c = AC.parse('# hi\napp.name: X\napp.ver: 2.0\napp.category: auto\napp.kind: buttons\n')
t.eq(c.get('name'), 'X', 'parse app.name')
t.eq(c.get('category'), 'auto', 'parse app.category')
t.eq(AC.auto_category('buttons', 'A = ble ping apple\nB = ble scan\n'), 'Wireless', 'auto -> Wireless (ble)')
t.eq(AC.auto_category('buttons', 'A = run ls\nB = run df\n'), 'System', 'auto -> System (run)')
t.eq(AC.auto_category('buttons', 'A = notify hi\n'), 'Tools', 'auto -> Tools (notify)')
t.eq(AC.auto_category('buttons', ''), 'Tools', 'empty -> Tools default')
t.eq(AC.category({'category': 'Sensors', 'kind': 'buttons'}), 'Sensors', 'explicit category wins')
t.eq(AC.category({'category': 'auto', 'kind': 'buttons'}, 'A = lora hi\n'), 'Wireless', 'auto resolves from content')

# --- novaappstore fetch + install (fake net reads the local store) ---
import types
def _fake_curl(url):
    return open(os.path.join(STORE, url.split('/repo/novad1-apps/', 1)[1])).read()
sys.modules['net'] = types.SimpleNamespace(curl=_fake_curl)
import novaappstore
import novastore
_saved = {}
novastore.save_code = lambda cat, n, txt: _saved.__setitem__((cat, n), txt)
novastore.list_codes = lambda cat: [k[1] for k in _saved if k[0] == cat]

got = novaappstore.fetch_index()
t.ok(got is not None and len(got) == len(apps), 'fetch_index returns all apps')
nm = novaappstore.install(got[0])
t.ok(nm and ('scripts', nm) in _saved, 'install saves the entry to the scripts store')
t.ok('ble' in _saved[('scripts', nm)].lower(), 'installed content is the app body')

sys.exit(t.done())
