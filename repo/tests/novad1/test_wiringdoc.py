# The wiring doc's pin tables are generated from novaboard's profiles. This asserts
# they're in sync, because the hand-maintained version DID drift: it had the status LED
# on GPIO 42 while the code used 48, and documented registry keys that never existed.
#
# The doc lives in the NovaLabs repo, so this skips cleanly when only this repo is
# checked out rather than failing for the wrong reason.
import os
import sys
import subprocess
import _shims
_shims.install()
from _shims import T

t = T('test_wiringdoc')

_HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.normpath(os.path.join(_HERE, '..', '..', 'tools', 'novad1', 'gen_wiring.py'))
DOC = os.path.normpath(os.path.join(_HERE, '..', '..', '..', '..',
                                    'NovaLabs', 'docs', 'novad1-wiring.md'))

t.ok(os.path.exists(GEN), 'the generator exists')

if not os.path.exists(DOC):
    print('  (skipped: NovaLabs/docs/novad1-wiring.md not present)')
    sys.exit(t.done())

r = subprocess.run([sys.executable, GEN, '--check'],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
out = r.stdout.decode('utf-8', 'replace').strip()
t.eq(r.returncode, 0,
     'wiring doc is in sync with the board profiles -- run gen_wiring.py\n    ' + out)

# --check must actually be able to fail, or it proves nothing.
text = open(DOC).read()
try:
    open(DOC, 'w').write(text.replace('| `ir_tx` | **39**', '| `ir_tx` | **99**', 1))
    r2 = subprocess.run([sys.executable, GEN, '--check'],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    t.eq(r2.returncode, 1, '--check reports a tampered table as out of date')
finally:
    open(DOC, 'w').write(text)

r3 = subprocess.run([sys.executable, GEN, '--check'],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
t.eq(r3.returncode, 0, 'and the doc was restored intact afterwards')

# Every board must appear in the doc, or someone reading it will miss a target.
import novaboard as nb
text = open(DOC).read()
for bid in nb.boards():
    t.ok(bid in text, 'wiring doc covers the {} profile'.format(bid))
    t.ok(nb.profile(bid).get('name', '') in text,
         'and names it as {}'.format(nb.profile(bid).get('name')))

# The reserved-GPIO warning is the one that stops a real hardware conflict.
for bid in nb.boards():
    for g in nb.profile(bid).get('reserved', ()):
        t.ok(str(g) in text, 'doc warns about reserved GPIO {}'.format(g))

# Board-agnostic module wiring: the per-module section must reference SIGNAL names,
# not per-board pin numbers, or it goes stale the moment a board is added.
for sig in ('`sda`', '`spi_sck`', '`cc_cs`', '`sx_rst`', '`ir_tx`', '`battery`'):
    t.ok(sig in text, 'module wiring refers to the {} signal'.format(sig))

sys.exit(t.done())
