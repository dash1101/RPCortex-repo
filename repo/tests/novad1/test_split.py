# novaservice must be SELF-CONTAINED.
#
# The GUI runner was split out of novad1 so the autostarted GUI does not load the
# ~44 KB shell CLI. That only works if novaservice can run without novad1 — and
# the first attempt could not: _build_ui passes _state_provider as a REFERENCE,
# and the dependency scan that drove the extraction only looked for `name(` call
# patterns, so it was left behind. The device booted, started the service, and
# died with "name '_state_provider' isn't defined".
#
# This checks the property directly instead of trusting a scan: parse novaservice,
# collect every name it reads, and insist each one is defined there, imported
# there, or a builtin. It catches references AND calls, so the shape of the miss
# cannot come back.
import ast
import os
import sys
import _shims
_shims.install()
from _shims import T

t = T('test_split')

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, '..', '..', 'packages', 'novad1'))
SVC = os.path.join(PKG, 'novaservice.py')
D1 = os.path.join(PKG, 'novad1.py')


def defined_and_imported(path):
    """Every name a module defines at top level, imports, or binds locally."""
    tree = ast.parse(open(path).read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            names.update(a.arg for a in node.args.args)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                for n in ast.walk(tgt):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                names.add((al.asname or al.name).split('.')[0])
        elif isinstance(node, (ast.For, ast.comprehension)):
            tgt = node.target
            for n in ast.walk(tgt):
                if isinstance(n, ast.Name):
                    names.add(n.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    for n in ast.walk(item.optional_vars):
                        if isinstance(n, ast.Name):
                            names.add(n.id)
        elif isinstance(node, ast.Global):
            names.update(node.names)
    return names


BUILTINS = set(dir(__builtins__) if isinstance(__builtins__, dict) is False
               else __builtins__.keys()) | {
    'True', 'False', 'None', 'self', 'const', 'micropython'}

svc_names = defined_and_imported(SVC) | BUILTINS
svc_reads = {n.id for n in ast.walk(ast.parse(open(SVC).read()))
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
unresolved = sorted(svc_reads - svc_names)

t.eq(unresolved, [],
     'novaservice resolves every name it uses without novad1 (missing: {})'
     .format(unresolved))

# The point of the split, stated as a test: importing the service must not drag
# in the command module.
import novaservice  # noqa
t.ok('novad1' not in sys.modules,
     'importing novaservice does NOT import novad1 (that is the whole point)')
t.ok('novagui' not in sys.modules,
     'nor novagui — the UI loads when the service actually starts')
t.ok(callable(novaservice.novagui), 'the shell entry point exists')
t.ok(callable(novaservice._gui_service), 'and the background runner')
t.ok(callable(novaservice._build_ui), 'and the UI builder')
t.ok(callable(novaservice._state_provider),
     'and the status provider it hands to the UI')

# novad1 must still work: its own commands use the moved helpers.
import novad1  # noqa
for name in ('_build_ui', '_state_provider', '_i2c_pins', '_gui_service',
             'set_web', '_nlog'):
    t.ok(hasattr(novad1, name),
         'novad1 still resolves {} (its commands use it)'.format(name))

# The autostart line must point at the light entry point, or the split buys
# nothing: `novad1 gui --bg` loads the CLI to reach the runner.
d1src = open(D1).read()
t.ok("'novagui --bg'" in d1src, 'setup registers the light autostart entry')
t.ok("services.cfg" in d1src, 'and writes it to services.cfg')
t.ok("'novad1 gui --bg' in existing" in d1src,
     'and migrates an existing install off the heavy one')

sys.exit(t.done())
