# kind:py apps — the loader (exec a downloaded app -> Screen factory), the sample Dice
# app, home integration, and the store routing. All against the real store dir.
import sys
import os
import types
import _shims
_shims.install()
from _shims import T
import novainput as ev

t = T('test_pyapps')
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'novad1-apps')
DICE = open(os.path.join(STORE, 'dice', 'dice.py')).read()

# --- the loader execs a kind:py app + returns its Screen factory + meta ---
import novaapps
fac, meta = novaapps.load_py_app(DICE)
t.ok(callable(fac), 'load_py_app returns a factory')
t.eq(meta['title'], 'Dice', 'meta title from TITLE')
t.eq(meta['category'], 'Tools', 'meta category from CATEGORY')

scr = fac()
t.ok(hasattr(scr, 'draw') and hasattr(scr, 'on_event'), 'factory builds a Screen')
scr.on_event(ev.SELECT)
t.ok(scr.rolling > 0, 'SELECT starts a roll')
scr.tick(500)
t.ok(1 <= scr.n <= 6, 'roll settles to a die face 1..6')
t.eq(scr.on_event(ev.BACK), ev.BACK, 'BACK exits')

class _C:
    w = 128
    h = 64
    def text(self, *a, **k):
        pass
scr.draw(_C())                              # renders without error

# bad / incomplete sources fail closed
t.eq(novaapps.load_py_app('not python !!!')[0], None, 'invalid source -> None')
t.eq(novaapps.load_py_app('x = 1')[0], None, 'source without app() -> None')

# --- the dice app.cfg is a valid kind:py entry ---
import novaappcfg as AC
cfg = AC.parse(open(os.path.join(STORE, 'dice', 'app.cfg')).read())
t.eq(cfg['kind'], 'py', 'dice app.cfg kind:py')
t.eq(cfg['entry'], 'dice.py', 'dice entry file')
t.ok(os.path.exists(os.path.join(STORE, 'dice', cfg['entry'])), 'entry file exists')

# --- home integration: an installed py app lands on the home in its category ---
import novastore
_pystore = {'dice.py': DICE}
novastore.list_codes = lambda cat: list(_pystore) if cat == 'pyapps' else []
novastore.read_code = lambda cat, n: _pystore.get(n) if cat == 'pyapps' else None
import novagui
pa = novagui._py_apps()
match = [a for a in pa if a[0] == 'pyapp_dice.py']
t.ok(match, 'installed py app appears on the home')
t.eq(novagui._app_category('pyapp_dice.py'), 'Tools', 'py app in its CATEGORY folder')
key, label, homefac = match[0]
t.eq(label, 'Dice', 'home label from TITLE')
t.ok(hasattr(homefac(), 'draw'), 'home factory builds the app screen')

# --- novaappstore routes a kind:py install to the pyapps store ---
import novaappstore
def _fake_curl(url):
    return open(os.path.join(STORE, url.split('/repo/novad1-apps/', 1)[1])).read()
sys.modules['net'] = types.SimpleNamespace(curl=_fake_curl)
saved = {}
novastore.save_code = lambda cat, n, txt: saved.__setitem__((cat, n), txt)
entry = novaappstore.install({'dir': 'dice'})
t.eq(entry, 'dice.py', 'install returns the entry name')
t.ok(('pyapps', 'dice.py') in saved, 'kind:py install saves to the pyapps store (not scripts)')

sys.exit(t.done())
