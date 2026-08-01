# novaicons: every app icon must actually DRAW, at both sizes the gallery uses.
#
# This exists because the failure mode here is silent. `draw()` wraps the lookup in
# a try/except and falls back to a box with the key's first letter, so a missing
# _MAP, a function that raises at one radius, or one that draws nothing all leave
# the module importable and the suite green while the device shows letters. That is
# exactly what happened once: an edit deleted the whole _MAP dict and nothing here
# noticed. The same reasoning as test_novafont (no solid/blank glyphs) and
# test_screenfit (nothing off the panel edge).
import sys
import _shims
_shims.install()
from _shims import T

import novacanvas
import novaicons
import novagui

t = T('test_novaicons')

# The two radii IconGallery actually passes — read from the class, not remembered,
# so this can't drift away from the real call site.
R_BIG = novagui.IconGallery.RBIG
R_SML = novagui.IconGallery.RSML
SIZES = (R_SML, R_BIG)


def _render(key, r):
    """Draw one icon on a blank canvas and return the lit pixels as a set."""
    c = novacanvas.Canvas(64, 64)
    novaicons.draw(c, key, 32, 32, r, key)
    lit = set()
    for y in range(64):
        for x in range(64):
            if (c.buf[(y >> 3) * c.w + x] >> (y & 7)) & 1:
                lit.add((x, y))
    return lit


keys = sorted(novaicons._MAP) + ['ir', 'ir_tx', 'ir_rx']

# ---------------------------------------------------------------- no silent fallback
# Compared per-key against that SAME key's fallback, not against one fixed image:
# the fallback draws the key's own first letter, so every key falls back to
# something different and a single reference would pass by accident.
_saved_map = novaicons._MAP
_saved_ir = novaicons._remote


def _boom(*a):
    raise RuntimeError('forced fallback')


for key in keys:
    for r in SIZES:
        real = _render(key, r)
        # _MAP alone isn't enough: draw() special-cases the IR keys BEFORE the
        # lookup, so _remote has to be knocked out too or those three compare
        # their real icon against their real icon and always "pass".
        novaicons._MAP = {}
        novaicons._remote = _boom
        try:
            fb = _render(key, r)
        finally:
            novaicons._MAP = _saved_map
            novaicons._remote = _saved_ir
        t.ok(real != fb and len(real) > 0,
             '{} draws its own icon at r={}'.format(key, r))

# ------------------------------------------------------------- readable when small
# An icon that scales down to a handful of pixels is a smudge on the home screen.
for key in keys:
    lit = _render(key, R_SML)
    t.ok(len(lit) >= 8, '{} still has a shape at neighbour size'.format(key))

# ------------------------------------------------------------------ stays in its box
# draw() is documented as rendering within half-size r; a glyph outside that is
# drawing over its neighbour in the gallery.
for key in keys:
    for r in SIZES:
        out = [p for p in _render(key, r)
               if abs(p[0] - 32) > r + 2 or abs(p[1] - 32) > r + 2]
        t.ok(not out, '{} stays within r={} (+2 slack)'.format(key, r))

# --------------------------------------------------- every key the GUI asks for exists
# Guards the category/menu edits: renaming a folder or adding one without adding its
# icon silently degrades that folder to a letter box.
for cat, key in sorted(novagui._CAT_ICON.items()):
    t.ok(key in novaicons._MAP,
         'category {} icon {} is mapped'.format(cat, key))

home = novagui.build_home({})
missing = []


def _walk(gallery, depth=0):
    """Only IconGallery entries carry an icon key in slot 0 — a Menu's slot 0 is a
    label, so descending into one and treating its rows as icon keys reports the
    whole UI as missing."""
    if depth > 3 or not isinstance(gallery, novagui.IconGallery):
        return
    for it in gallery.items:
        key = it[0]
        if key not in novaicons._MAP and not key.startswith(('script_', 'ir')):
            missing.append(key)
        sub = it[2] if len(it) > 2 else None
        if callable(sub):
            try:
                child = sub()
            except Exception:
                continue
            _walk(child, depth + 1)


_walk(home)
t.eq(missing, [], 'every home/folder entry has a mapped icon')

sys.exit(t.done())
