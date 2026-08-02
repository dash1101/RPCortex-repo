# File Explorer: browse the device filesystem from the panel.
#
# Read-only on purpose. Browsing and previewing cannot lose anything; deleting
# from a 128x64 panel with three buttons can, and the shell already has `rm` with
# a prompt.
#
# The control worth guarding is BACK: in a file explorer it goes UP a directory,
# and only leaves the app once you are at the root. Getting that wrong makes the
# app unusable at depth, and it is exactly the kind of thing a refactor breaks.
import sys
import os
import shutil
import tempfile
import _shims
_shims.install()
from _shims import T

import novacanvas
import novainput as ev
import novagui_files as F

t = T('test_files')

# A real tree on disk — the shims stub `machine`, not the filesystem, so this
# exercises the actual uos calls the device makes.
ROOT = tempfile.mkdtemp()
os.makedirs(os.path.join(ROOT, 'Vela', 'nova'))
os.makedirs(os.path.join(ROOT, 'Apps'))
open(os.path.join(ROOT, 'boot.py'), 'w').write('print("hi")\n' * 3)
open(os.path.join(ROOT, 'notes.txt'), 'w').write('line one\nline two\n')
open(os.path.join(ROOT, 'blob.bin'), 'wb').write(b'\x00' * 4096)
open(os.path.join(ROOT, 'Vela', 'nova', 'deep.cfg'), 'w').write('k=v\n')

c = novacanvas.Canvas(128, 64)

# ------------------------------------------------------------------- listing
rows = F.listing(ROOT)
names = [r[0] for r in rows]
t.ok('boot.py' in names and 'Apps' in names, 'it lists what is there')
dirs = [r[0] for r in rows if r[1]]
files = [r[0] for r in rows if not r[1]]
t.eq(names[:len(dirs)], dirs,
     'directories come first, so a tree is navigable without hunting')
t.eq(dirs, sorted(dirs, key=str.lower), 'directories are sorted')
t.eq(files, sorted(files, key=str.lower), 'and so are files')
t.ok(F.listing(os.path.join(ROOT, 'nope')) == [],
     'a missing directory lists empty rather than raising')

sz = dict((r[0], r[2]) for r in rows)
t.eq(sz['blob.bin'], 4096, 'file sizes are real')
t.eq(sz['Apps'], 0, 'directories report no size')

t.eq(F._human(512), '512B', 'bytes')
t.eq(F._human(2048), '2K', 'kilobytes')
t.eq(F._human(1024 * 1024 * 3 // 2), '1.5M', 'megabytes')

t.eq(F._parent('/Vela/nova'), '/Vela', 'parent of a nested path')
t.eq(F._parent('/Vela'), '/', 'parent of a top-level path is the root')
t.eq(F._parent('/'), '/', 'the root is its own parent -- no walking off the top')
t.eq(F._join('/', 'x'), 'x', 'joining at the root does not double the slash')
t.eq(F._join('/Vela', 'x'), '/Vela/x', 'and joins normally below it')

# ------------------------------------------------------------------ browsing
s = F.FilesScreen(ROOT)
t.ok(s.entries, 'the screen loads a listing')
# The title has to be right BEFORE the first draw: the runner paints the status
# bar from scr.title and then calls draw(), so a title computed during the draw
# arrives a frame late and every directory shows the previous one's name.
t.eq(s.title, ROOT.rsplit('/', 1)[-1],
     'the title names the current directory from the moment it is constructed')
s.draw(c)

# Enter a directory.
s.sel = [i for i, r in enumerate(s.entries) if r[0] == 'Vela'][0]
t.eq(s.on_event(ev.SELECT), None, 'opening a folder stays in the app')
t.ok(s.path.endswith('Vela'), 'and moves into it')
t.eq(s.title, 'Vela', 'the title follows immediately, without waiting for a draw')
t.eq(s.sel, 0, 'with the selection reset to the top')

# BACK goes UP, not out. This is the whole point.
t.eq(s.on_event(ev.BACK), None, 'BACK inside a folder does not leave the app')
t.eq(s.path, ROOT, 'it goes up a level')

# ...and only leaves once there is nowhere further up.
root = F.FilesScreen('/')
t.eq(root.on_event(ev.BACK), ev.BACK, 'BACK at the root leaves the app')
t.eq(F.FilesScreen(ROOT).on_event(ev.HOME), ev.HOME, 'HOME always quits')

# The selection wraps rather than sticking at the ends.
s2 = F.FilesScreen(ROOT)
n = len(s2.entries)
s2.sel = n - 1
s2.on_event(ev.ROT_CW)
t.eq(s2.sel, 0, 'turning past the last entry wraps to the first')
s2.on_event(ev.ROT_CCW)
t.eq(s2.sel, n - 1, 'and back the other way')

# An empty folder draws a message instead of nothing at all.
empty = F.FilesScreen(os.path.join(ROOT, 'Apps'))
empty.draw(c)
t.eq(empty.entries, [], 'an empty folder has no entries')
t.ok(True, 'and still draws')

# ------------------------------------------------------------------ opening
s3 = F.FilesScreen(ROOT)
s3.sel = [i for i, r in enumerate(s3.entries) if r[0] == 'notes.txt'][0]
scr = s3.on_event(ev.SELECT)
t.eq(scr.__class__.__name__, 'PreviewScreen', 'a text file opens a preview')
t.ok(any('line one' in ln for ln in scr.lines), 'showing its contents')
scr.draw(c)
t.eq(scr.on_event(ev.BACK), ev.BACK, 'and BACK closes it')

s3.sel = [i for i, r in enumerate(s3.entries) if r[0] == 'blob.bin'][0]
info = s3.on_event(ev.SELECT)
t.eq(info.__class__.__name__, 'InfoScreen',
     'a binary file shows details rather than a meaningless preview')
info.draw(c)
t.ok(any(k == 'Size' for k, _v in info.rows), 'including its size')

# A preview is BOUNDED. One enormous file must not be pulled into a heap with
# about 90 KB free.
big = os.path.join(ROOT, 'big.log')
open(big, 'w').write('x' * 200000)
pv = F.PreviewScreen(big)
t.ok(len(pv.lines) <= 121,
     'a huge file is capped at a screenful of lines, not read whole')
t.ok(F.PREVIEW_BYTES <= 4096, 'and the read itself is capped in bytes')

# An unreadable file reports why instead of raising into the draw loop.
missing = F.PreviewScreen(os.path.join(ROOT, 'gone.txt'))
t.ok(missing.lines, 'a missing file still produces something to show')

# An empty file says so rather than looking broken.
open(os.path.join(ROOT, 'nil.txt'), 'w').close()
t.ok('empty' in ' '.join(F.PreviewScreen(os.path.join(ROOT, 'nil.txt')).lines),
     'an empty file says it is empty')

# ------------------------------------------------------------- folder picking
# The hook a music player would use to choose a queue folder.
picked = []
p = F.FilesScreen(ROOT, on_pick=picked.append)
t.eq(p.on_event(ev.SELECT_HOLD), 'back', 'holding SELECT returns the folder')
t.eq(picked, [ROOT], 'handing the caller the current path')

# Without a picker it is simply inert, not an error.
t.eq(F.FilesScreen(ROOT).on_event(ev.SELECT_HOLD), None,
     'and with no picker attached it does nothing')

# ------------------------------------------------------------------ bounded
t.ok(F.MAX_ENTRIES <= 500,
     'a listing is capped -- a runaway log directory should slow the screen '
     'down, not exhaust the heap')

# ------------------------------------------------------------- read-only
import inspect
src = inspect.getsource(F)
for danger in ('.remove(', '.rmdir(', 'shutil'):
    t.ok(danger not in src,
         'the explorer never deletes ({} absent) -- three buttons and a 128x64 '
         'panel is the wrong place to confirm a delete'.format(danger))
t.ok("open(path, 'w')" not in src, 'and never writes')

t.ok(F.FilesScreen.help, 'it documents its controls')
for ln in F.FilesScreen.help:
    t.ok(c.text_width(ln) <= c.w - 4, 'help line {!r} fits'.format(ln))

shutil.rmtree(ROOT, ignore_errors=True)
sys.exit(t.done())
