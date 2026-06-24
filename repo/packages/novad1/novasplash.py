# Desc: Nova D1 startup splash — animated RPCortex / Nova D1 reveal.
# File: /Packages/NovaD1/novasplash.py
#
# draw(c, t) paints one frame for progress t in 0..1 (the SplashScreen advances t
# by dt). Sequence: a power-on ring pulse, then "Nova D1" (big) wipes in left to
# right, then "RPCortex" + a growing underline. Pure primitives -> cheap + slick
# on the 1-bit panel, and renders identically on the PC mock.

import novafont as _f


def _clamp(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def draw(c, t):
    c.clear(0)
    w = c.w
    h = c.h
    cx = w // 2
    cy = h // 2 - 2

    # 1) power-on ring pulse (early)
    if t < 0.45:
        p = t / 0.4
        r = int(p * (w // 2 + 6))
        if 0 < r < w:
            c.circle(cx, cy, r, 1)
            if r > 7:
                c.circle(cx, cy, r - 7, 1)

    # 2) "Nova D1" big (scale 2), wiped in left->right
    title = 'Nova D1'
    tw = len(title) * _f.ADVANCE * 2
    tx = (w - tw) // 2
    ty = cy - _f.HEIGHT
    c.text(tx, ty, title, 1, 2)
    rev = _clamp((t - 0.22) / 0.4)
    hx = tx + int(rev * tw)
    if hx < tx + tw:
        c.fill_rect(hx, ty - 2, w - hx, _f.HEIGHT * 2 + 4, 0)

    # 3) "RPCortex" + underline
    if t > 0.5:
        sub = 'RPCortex'
        sw = len(sub) * _f.ADVANCE
        c.text((w - sw) // 2, ty + _f.HEIGHT * 2 + 5, sub, 1)
    uw = int(_clamp((t - 0.55) / 0.45) * (w - 20))
    if uw > 0:
        c.hline(10, h - 3, uw, 1)
        c.hline(10, h - 2, uw, 1)
