# novacore: the shared cross-cutting leaf. reg()/save_reg() contract + the delegation
# that replaced ~12 copies of _reg across the package.
import sys
import _shims
_shims.install()
from _shims import T
import novacore

t = T('test_novacore')

_shims.set_reg({'A.B': 'hello', 'E.F': ''})
t.eq(novacore.reg('A.B'), 'hello', 'reads a set key')
t.eq(novacore.reg('E.F', 'dflt'), 'dflt', 'empty value counts as absent -> default')
t.eq(novacore.reg('No.Key', 'dflt'), 'dflt', 'missing key -> given default')
t.eq(novacore.reg('No.Key'), None, 'missing key -> None default')
t.ok(novacore.save_reg('X.Y', 'z'), 'save_reg returns True on success')
t.eq(novacore.reg('X.Y'), 'z', 'saved value round-trips')

# every migrated module actually imports and shares the one implementation (no copies).
# This import-exercises the whole set — ast.parse alone wouldn't prove the delegation
# resolves at load time (the gap the browser sim's fetch-list would otherwise hide).
for mod in ('novacc', 'novacrypt', 'novair', 'novalora', 'novamods', 'novanotify',
            'novapower', 'novartc', 'novasound', 'novaweb', 'novad1'):
    m = __import__(mod)
    t.ok(getattr(m, '_reg', None) is novacore.reg, '{} delegates _reg to novacore'.format(mod))
import novagui
t.ok(novagui._reg is novacore.reg, 'novagui delegates _reg to novacore')
t.ok(novagui._save_reg is novacore.save_reg, 'novagui delegates _save_reg to novacore')

sys.exit(t.done())
