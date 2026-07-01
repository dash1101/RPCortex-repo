# App store: every app listed in novad1-apps/index.json must exist and parse as a
# valid button-grid (so a broken store app is caught before it ships).
import sys
import os
import json
import _shims
_shims.install()
from _shims import T
import nova

t = T('test_appstore')

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'novad1-apps')
idx = json.load(open(os.path.join(STORE, 'index.json')))
apps = idx.get('apps', [])
t.ok(len(apps) >= 1, 'index lists at least one app')

cats = ('Wireless', 'Sensors', 'Tools', 'System')
for a in apps:
    name = a.get('name', '?')
    for field in ('name', 'file', 'category', 'kind'):
        t.ok(field in a, "{}: has '{}'".format(name, field))
    t.ok(a.get('category') in cats, "{}: category is a home folder".format(name))
    path = os.path.join(STORE, a['file'])
    t.ok(os.path.exists(path), "{}: file exists ({})".format(name, a.get('file')))
    if a.get('kind') == 'buttons' and os.path.exists(path):
        title, btns = nova.parse_buttons(open(path).read())
        t.ok(len(btns) >= 1, "{}: parses to >=1 button".format(name))
        # every action must be a known verb the do() dispatcher handles
        verbs = ('ir', 'subghz', 'lora', 'ble', 'run', 'notify', 'sleep', 'log')
        bad = [lbl for lbl, act in btns if act.split(None, 1)[0] not in verbs]
        t.ok(not bad, "{}: all actions use a known verb (bad: {})".format(name, bad))

sys.exit(t.done())
