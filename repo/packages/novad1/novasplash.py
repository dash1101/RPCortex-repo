# Desc: Nova D1 startup splash — animated RPCortex / Nova D1 reveal.
# File: /Packages/NovaD1/novasplash.py
#
# draw(c, t) paints one frame for progress t in 0..1 (the SplashScreen advances t
# by dt). Sequence: a power-on ring pulse, then "Nova D1" (big) wipes in left to
# right, then "RPCortex" + a growing underline. Pure primitives -> cheap + slick
# on the 1-bit panel, and renders identically on the PC mock.

# Deliberately NO font import. The canvas renders text with whichever font it is
# built against, and measuring with a different one puts everything off-centre —
# which is exactly what happened when the UI moved to the 5x7 font while this
# still measured with the 8x8 one's advance, centring "Nova D1" as though it were
# a third wider than it draws. c.text_width() always agrees with c.text().


def _clamp(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def _centre_x(c, s, scale=1):
    """x for text visually centred on the panel.

    text_width() measures ADVANCE, which includes the blank gap after the last
    glyph — centring on that leaves the text a couple of pixels left of centre.
    Subtracting the final glyph's trailing gap centres the INK, which is what the
    eye judges. Uses only canvas calls, so it cannot disagree with the font the
    canvas actually draws with."""
    w = c.text_width(s, scale)
    try:
        adv = c.text_width('M', 1)
        w -= (adv - c.glyph_w(ord(s[-1]))) * scale
    except Exception:
        pass
    return (c.w - w) // 2


def _glyph_h(c):
    """Glyph height of whatever font the canvas actually uses."""
    try:
        import novafont5x7 as _f
        return _f.HEIGHT
    except Exception:
        return 8


def draw(c, t):
    c.clear(0)
    w = c.w
    h = c.h
    cx = w // 2
    cy = h // 2 - 2

    # 2) "Nova D1" big (scale 2), wiped in left->right
    title = 'Nova D1'
    tw = c.text_width(title, 2)
    th = _glyph_h(c) * 2
    tx = _centre_x(c, title, 2)
    ty = cy - _glyph_h(c)
    c.text(tx, ty, title, 1, 2)
    rev = _clamp((t - 0.22) / 0.4)
    hx = tx + int(rev * tw)
    if hx < tx + tw:
        c.fill_rect(hx, ty - 2, w - hx, th + 4, 0)

    # The ring is drawn AFTER the title wipe, not before it. The wipe blanks the
    # whole title band to reveal the letters left-to-right, and the ring is
    # centred inside that band — drawn first, it was simply erased, which is why
    # frame t=0 came out completely blank and the panel looked dead for a beat.
    if t < 0.45:
        p = t / 0.4
        r = 6 + int(p * (w // 2))
        if 0 < r < w:
            c.circle(cx, cy, r, 1)
            if r > 13:
                c.circle(cx, cy, r - 7, 1)

    # 3) "RPCortex" + underline
    if t > 0.5:
        sub = 'RPCortex'
        c.text(_centre_x(c, sub), ty + th + 5, sub, 1)
    uw = int(_clamp((t - 0.55) / 0.45) * (w - 20))
    if uw > 0:
        c.hline(10, h - 3, uw, 1)
        c.hline(10, h - 2, uw, 1)
