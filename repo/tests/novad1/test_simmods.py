# The browser simulator fetches a HARDCODED list of module filenames (const MODS in
# NovaLabs/d1-sim.html). A module missing from that list is fatal at load if anything
# imports it at TOP LEVEL — which is exactly what happened to novafont5x7: novacanvas
# imports it unconditionally, it was never added to MODS, and the sim died on start.
#
# A lazy import inside a function is a different case: it sits behind a try/except, so
# the feature degrades instead of the sim dying. Only top-level imports are asserted.
import os
import re
import sys
import _shims
_shims.install()
from _shims import T

t = T('test_simmods')

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, '..', '..', 'packages', 'novad1'))
SIM = os.path.normpath(os.path.join(
    HERE, '..', '..', '..', '..', 'NovaLabs', 'd1-sim.html'))

if not os.path.exists(SIM):
    t.ok(True, 'sim not present in this checkout — skipped')
    sys.exit(t.done())

html = open(SIM).read()
block = html[html.index('const MODS = ['):]
block = block[:block.index('];')]
mods = set(re.findall(r"'([^']+)'", block))
t.ok(len(mods) > 10, 'the MODS list parsed ({} modules)'.format(len(mods)))

local = set(f[:-3] for f in os.listdir(PKG) if f.endswith('.py'))

# The other direction: a name in MODS with no file behind it is a 404 at load.
for name in sorted(mods):
    t.ok(name in local, 'MODS entry {!r} has a file'.format(name))
_TOP_IMPORT = re.compile(r'^(?:import|from)\s+(\w+)', re.M)

for name in sorted(mods & local):
    src = open(os.path.join(PKG, name + '.py')).read()
    for dep in sorted(set(_TOP_IMPORT.findall(src))):
        if dep in local and dep not in mods:
            t.ok(False, '{} imports {} at top level, but {} is not in MODS'.format(
                name, dep, dep))

t.ok(True, 'every top-level dependency of a simulated module is in MODS')
sys.exit(t.done())
