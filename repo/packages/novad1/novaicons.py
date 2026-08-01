# Desc: Nova D1 app icons — procedural 1-bit glyphs drawn with canvas primitives.
# File: /Packages/NovaD1/novaicons.py
#
# draw(c, key, cx, cy, r) renders the icon for `key` centered at (cx,cy) within a
# half-size r (so the gallery's center icon is big, neighbours small — same code,
# different r). Primitives only (no bitmap blobs), so they scale + draw cheaply.
# The label under the centred icon does the identifying; the icon is support.
# MicroPython-safe: no f-strings.


def _box(c, cx, cy, r, col=1):
    c.rect(cx - r, cy - r, 2 * r, 2 * r, col)


def _rbox(c, x, y, w, h, col=1):
    """A rectangle with its corners knocked off. Everything on this panel is
    drawn from straight lines, so a screen full of hard-cornered boxes reads as
    unfinished; a single pixel off each corner is enough to soften it without
    costing legibility at neighbour size."""
    if w < 4 or h < 4:
        c.rect(x, y, w, h, col)
        return
    c.hline(x + 1, y, w - 2, col)
    c.hline(x + 1, y + h - 1, w - 2, col)
    c.vline(x, y + 1, h - 2, col)
    c.vline(x + w - 1, y + 1, h - 2, col)



def _thermo(c, cx, cy, r):            # DHT11 — thermometer
    bulb = max(2, r // 2)
    by = cy + r - bulb
    c.fill_circle(cx, by, bulb, 1)
    tw = max(2, bulb - 1)                       # tube width tracks the bulb
    ty = cy - r
    c.rect(cx - tw // 2, ty, tw + 1, by - ty, 1)
    for i in range(3):                          # graduations on the right
        yy = ty + 3 + i * max(2, (by - ty - 5) // 3)
        if yy < by - bulb:
            c.hline(cx + tw // 2 + 2, yy, max(2, r // 3), 1)



def _pin(c, cx, cy, r):               # GPS — map pin
    # A ring on a teardrop whose point reaches the bottom of the cell, so it reads
    # as "planted" rather than as a balloon.
    hr = max(2, (2 * r) // 5)
    hy = cy - r + hr + 1
    c.circle(cx, hy, hr, 1)
    c.circle(cx, hy, max(1, hr // 2), 1)
    tip = cy + r
    c.line(cx - hr, hy + hr // 2, cx, tip, 1)
    c.line(cx + hr, hy + hr // 2, cx, tip, 1)


def _nfc(c, cx, cy, r):               # NFC — a card with contactless waves
    w = r                                    # card occupies the left half
    _rbox(c, cx - r, cy - r // 2, w, r)
    c.hline(cx - r + 2, cy - r // 4, max(2, w // 2), 1)     # chip
    for i in range(1, 4):                                   # waves off the right
        rr = (r * i) // 3
        c.line(cx + rr // 2, cy - rr, cx + rr, cy, 1)
        c.line(cx + rr, cy, cx + rr // 2, cy + rr, 1)



def _radio(c, cx, cy, r):             # Sub-GHz/CC1101 — a transmitter mast
    # A braced mast, not a whip: this is the shape that tells CC1101 apart from
    # the LoRa antenna at a glance.
    base = cy + r
    top = cy - r // 2
    sp = max(2, r // 2)
    c.line(cx - sp, base, cx, top, 1)
    c.line(cx + sp, base, cx, top, 1)
    for i in (1, 2):                                    # cross-braces
        yy = base - (base - top) * i // 3
        hw = sp * (3 - i) // 3
        c.hline(cx - hw, yy, 2 * hw + 1, 1)
    c.fill_circle(cx, top, 1, 1)
    for i in (1, 2):                                    # emission chevrons
        s = i * max(2, r // 2)
        c.line(cx - s, top - s // 3, cx - s // 2, top + s // 4, 1)
        c.line(cx + s, top - s // 3, cx + s // 2, top + s // 4, 1)



def _antenna(c, cx, cy, r):           # LoRa/SX1276 — a whip antenna radiating
    # A straight rod on a foot, radiating upward. The tower shape is CC1101's; the
    # two have to be told apart at neighbour size, so they don't share a silhouette.
    base = cy + r - 1
    tip = cy - r // 3
    c.vline(cx, tip, base - tip, 1)
    c.hline(cx - max(2, r // 3), base, 2 * max(2, r // 3) + 1, 1)
    c.fill_circle(cx, tip, 1, 1)
    for i in (1, 2):
        _uarc(c, cx, tip, i * max(2, r // 3))


def _bt(c, cx, cy, r):                # Bluetooth rune
    c.vline(cx, cy - r, 2 * r, 1)
    c.line(cx, cy - r, cx + r // 2, cy - r // 2, 1)
    c.line(cx + r // 2, cy - r // 2, cx, cy, 1)
    c.line(cx, cy, cx + r // 2, cy + r // 2, 1)
    c.line(cx + r // 2, cy + r // 2, cx, cy + r, 1)
    c.line(cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2, 1)
    c.line(cx - r // 2, cy + r // 2, cx + r // 2, cy - r // 2, 1)


def _remote(c, cx, cy, r, up):        # IR — an emitter/receiver with a beam
    # The body sits at the bottom, the beam fans upward (TX) or inward (RX), and
    # both scale from r so the shape survives being shrunk to a neighbour icon.
    bw, bh = r, max(3, r)
    c.rect(cx - bw // 2, cy + r - bh, bw, bh, 1)
    c.hline(cx - bw // 2 + 1, cy + r - bh + 2, max(1, bw - 2), 1)
    tip = cy + r - bh
    for i in (0, 1, 2):
        span = max(2, (r * (i + 1)) // 3)
        yy = tip - span
        if up:
            c.line(cx - span // 2, yy, cx, tip - 1, 1)
            c.line(cx + span // 2, yy, cx, tip - 1, 1)
        else:
            c.hline(cx - span // 2, yy, span, 1)


def _key(c, cx, cy, r):               # iButton — key
    c.circle(cx - r // 2, cy, r // 2, 1)
    c.hline(cx - r // 2, cy, 2 * r - r // 2, 1)
    c.vline(cx + r - 2, cy, r // 2, 1)
    c.vline(cx + r // 2, cy, r // 3, 1)


def _sd(c, cx, cy, r):                # SD card — notched rectangle
    c.line(cx - r + 2, cy - r, cx + r, cy - r, 1)
    c.line(cx + r, cy - r, cx + r, cy + r, 1)
    c.line(cx + r, cy + r, cx - r, cy + r, 1)
    c.line(cx - r, cy + r, cx - r, cy - r + 3, 1)
    c.line(cx - r, cy - r + 3, cx - r + 2, cy - r, 1)
    for i in range(3):
        c.vline(cx - r // 3 + i * 3, cy - r + 1, 3, 1)


def _battery(c, cx, cy, r):
    c.rect(cx - r, cy - r // 2, 2 * r - 1, r, 1)
    c.fill_rect(cx + r - 1, cy - r // 4, 2, r // 2, 1)
    c.fill_rect(cx - r + 2, cy - r // 2 + 2, r, r - 4, 1)


def _speaker(c, cx, cy, r):           # buzzer
    c.fill_rect(cx - r, cy - r // 3, r // 2, 2 * (r // 3), 1)
    c.line(cx - r // 2, cy - r // 3, cx, cy - r, 1)
    c.line(cx - r // 2, cy + r // 3, cx, cy + r, 1)
    c.vline(cx, cy - r, 2 * r, 1)
    c.line(cx + r // 2, cy - r // 2, cx + r, cy - r, 1)
    c.line(cx + r // 2, cy + r // 2, cx + r, cy + r, 1)


def _vibe(c, cx, cy, r):              # vibration — phone + waves
    _rbox(c, cx - r // 2, cy - r, r, 2 * r)
    for i in range(2):
        c.vline(cx - r + i * 2, cy - r // 2, r, 1)
        c.vline(cx + r // 2 + 1 + i * 2, cy - r // 2, r, 1)


def _led(c, cx, cy, r):               # status LED — sun/glow
    c.fill_circle(cx, cy, max(2, r // 2), 1)
    for a in ((-r, 0), (r, 0), (0, -r), (0, r),
              (-r, -r), (r, r), (-r, r), (r, -r)):
        c.line(cx + a[0] // 2, cy + a[1] // 2, cx + a[0], cy + a[1], 1)



def _wifi(c, cx, cy, r):
    # Three solid arcs over a dot. Drawn with a real arc walker (see _uarc) — the
    # old per-column circle sample left gaps and shattered at neighbour size.
    base = cy + r - 1
    c.fill_circle(cx, base, max(1, r // 5), 1)
    step = max(2, r // 3)
    for i in (1, 2, 3):
        _uarc(c, cx, base, i * step)


def _doc(c, cx, cy, r):               # Logs — a page of lines with a folded corner
    w, h = int(1.4 * r), 2 * r
    x, y = cx - w // 2, cy - r
    fold = max(2, r // 3)
    c.hline(x, y, w - fold, 1)
    c.line(x + w - fold, y, x + w - 1, y + fold, 1)         # folded corner
    c.vline(x + w - 1, y + fold, h - fold, 1)
    c.vline(x, y, h, 1)
    c.hline(x, y + h - 1, w, 1)
    for i in range(3):                                      # text lines
        yy = y + fold + 2 + i * max(2, (h - fold - 4) // 3)
        if yy < y + h - 2:
            c.hline(x + 2, yy, w - 5, 1)


def _gear(c, cx, cy, r):              # Settings — a gear
    # Built by CUTTING teeth out of a solid disc rather than sticking blocks on
    # a ring. The ring-plus-blocks version, with a circle in the middle, read as
    # a revolver cylinder — the teeth have to interrupt the rim silhouette to
    # look like a gear at all.
    body = max(3, r - 1)
    c.fill_circle(cx, cy, body, 1)
    notch = max(1, body // 3)
    d = body                                     # cut notches ON the rim
    for i in range(8):
        a = i * 0.7854                           # 45 degrees
        # cos/sin of multiples of 45 degrees, without importing math
        cs = (1, 0.7071, 0, -0.7071, -1, -0.7071, 0, 0.7071)[i]
        sn = (0, 0.7071, 1, 0.7071, 0, -0.7071, -1, -0.7071)[i]
        nx = int(cx + cs * d)
        ny = int(cy + sn * d)
        c.fill_rect(nx - notch // 2, ny - notch // 2, notch, notch, 0)
    hole = max(1, body // 3)
    c.fill_circle(cx, cy, hole, 0)               # the bore
    c.circle(cx, cy, hole, 1)


def _check(c, cx, cy, r):             # System Check — clipboard + tick
    w = 2 * r - 2
    _rbox(c, cx - r + 1, cy - r + 2, w, 2 * r - 3)
    clip = max(2, r // 2)                       # clip scales with the board
    c.fill_rect(cx - clip // 2, cy - r, clip, max(2, r // 3), 1)
    t = max(2, r // 3)
    c.line(cx - t, cy + 1, cx - 1, cy + t, 1)   # tick
    c.line(cx - 1, cy + t, cx + t + 1, cy - t, 1)


def _chat(c, cx, cy, r):              # Messages — a rounded speech bubble
    w, h = 2 * r, int(1.3 * r)
    x, y = cx - r, cy - r
    # rounded body: corners knocked out so it reads soft rather than boxy
    c.hline(x + 1, y, w - 2, 1)
    c.hline(x + 1, y + h, w - 2, 1)
    c.vline(x, y + 1, h - 1, 1)
    c.vline(x + w - 1, y + 1, h - 1, 1)
    tail = max(2, r // 3)                                   # tail from the bottom
    c.line(x + tail, y + h, x + tail, y + h + tail, 1)
    c.line(x + tail, y + h + tail, x + tail * 2 + 1, y + h, 1)
    for i in range(3):                                      # message dots
        c.pixel(x + (w // 4) * (i + 1), y + h // 2, 1)


def _power(c, cx, cy, r):             # power symbol (ring + break + stem)
    c.circle(cx, cy, r - 1, 1)
    c.fill_rect(cx - 2, cy - r - 1, 5, 4, 0)
    c.vline(cx, cy - r - 1, r + 2, 1)



def _notes(c, cx, cy, r):             # Notifications — a bell
    # Built by mirroring around cx, so it can never end up visually off-centre.
    top = cy - r + 1
    rim = cy + r - max(2, r // 3) - 1
    hw = r - 1                                   # half width at the rim
    cr = max(2, hw // 2)                         # radius of the domed crown
    c.vline(cx, top - 1, max(1, r // 4), 1)      # the little knob
    _uarc(c, cx, top + cr, cr)                   # dome
    for sgn in (-1, 1):                          # shoulders flaring to the rim
        c.line(cx + sgn * cr, top + cr, cx + sgn * hw, rim, 1)
    c.hline(cx - hw, rim, 2 * hw + 1, 1)         # rim, two rows so it reads solid
    c.hline(cx - hw + 1, rim + 1, 2 * hw - 1, 1)
    c.fill_circle(cx, rim + max(2, r // 3), max(1, r // 4), 1)      # clapper


def _clock(c, cx, cy, r):             # Clock — dial + hands
    c.circle(cx, cy, r - 1, 1)
    c.line(cx, cy, cx, cy - (r - 4), 1)          # hour hand (up)
    c.line(cx, cy, cx + (r - 3), cy, 1)          # minute hand (right)
    c.pixel(cx, cy, 1)



def _wrench(c, cx, cy, r):            # Tools — an open-ended wrench
    # The handle leaves the RIM of the jaw, not its centre — drawn from the centre
    # it ran straight through the head, which is what made this look wrong. It is
    # offset by whole pixels in x and y (NOT perpendicular): a 45-degree line
    # offset perpendicular leaves a checkerboard and the handle looks dashed.
    head = max(2, r // 2)
    hx, hy = cx - r + head + 1, cy - r + head + 1
    sx, sy = hx + head, hy + head
    tx, ty = cx + r - 1, cy + r - 1
    c.line(sx, sy, tx, ty, 1)
    c.line(sx + 1, sy, tx, ty - 1, 1)
    c.line(sx, sy + 1, tx - 1, ty, 1)
    c.fill_circle(hx, hy, head, 1)                              # jaw...
    c.fill_circle(hx, hy, max(1, head - 2), 0)                  # ...hollowed
    c.fill_rect(hx - head - 1, hy - head - 1, head, head, 0)     # mouth, open


def _terminal(c, cx, cy, r):          # Commands — terminal window, prompt scales
    _rbox(c, cx - r, cy - r + 1, 2 * r, 2 * r - 2)
    c.hline(cx - r, cy - r + 1 + max(2, r // 3), 2 * r, 1)      # title bar
    k = max(2, r // 3)                                          # chevron size
    px, py = cx - r + max(2, r // 3), cy
    c.line(px, py - k, px + k, py, 1)                           # '>' as lines so it
    c.line(px + k, py, px, py + k, 1)                           # scales with r
    c.hline(px + k + 2, py + k, max(2, r - k), 1)               # cursor


def _store(c, cx, cy, r):             # App Store — a shopping bag with a handle
    # Body: a bag that is clearly a bag (tapered top edge), not a bare square.
    bx, by = cx - r + 2, cy - r + 5
    bw, bh = 2 * r - 4, 2 * r - 7
    _rbox(c, bx, by, bw, bh)
    c.hline(bx + 1, by + 2, bw - 2, 1)          # seam under the opening
    # Handle: a proper arch above the bag, sized from the bag width.
    hw = max(2, bw // 4)
    hy = by - 3
    c.vline(cx - hw, hy + 1, 3, 1)
    c.vline(cx + hw, hy + 1, 3, 1)
    c.hline(cx - hw + 1, hy, 2 * hw - 1, 1)


def _stethoscope(c, cx, cy, r):       # Hardware — a monitor showing a pulse
    # Every coordinate derives from r. The old version used fixed offsets (+5,
    # +7, +11 ...) that did not shrink with the icon, so at neighbour size the
    # trace ran straight out through the side of the box.
    x, y = cx - r, cy - r + 2
    w, h = 2 * r, 2 * r - 4
    _rbox(c, x, y, w, h)
    mid = cy
    step = max(1, w // 8)                       # one eighth of the width per leg
    amp = max(2, h // 3)
    px = x + 2
    c.hline(px, mid, step, 1)                   # flat lead-in
    px += step
    c.line(px, mid, px + step, mid - amp, 1)    # up
    px += step
    c.line(px, mid - amp, px + step, mid + amp, 1)   # down through the baseline
    px += step
    c.line(px, mid + amp, px + step, mid, 1)    # back up
    px += step
    c.hline(px, mid, max(1, x + w - 2 - px), 1)      # flat run to the edge


def _wardrive(c, cx, cy, r):          # Wardrive — a car under a broadcast arc
    # Outlined, not filled: a solid car collapses into an unreadable blob at
    # neighbour size, which is exactly what it used to do.
    bw = 2 * r - 2
    bx = cx - bw // 2
    wheel = max(1, r // 4)
    base = cy + r - wheel                        # axle line
    bh = max(2, r // 3)
    _rbox(c, bx, base - bh, bw, bh)              # lower body
    ch = max(2, r // 3)                          # cabin, inset both sides
    inset = max(1, bw // 5)
    _rbox(c, bx + inset, base - bh - ch + 1, bw - 2 * inset, ch)
    c.fill_rect(bx + inset + 1, base - bh, bw - 2 * inset - 2, 1, 0)
    c.circle(bx + inset, base, wheel, 1)         # wheels
    c.circle(bx + bw - inset, base, wheel, 1)
    _uarc(c, cx, base - bh - ch - 1, max(3, r - 1))          # the sweep overhead
    _uarc(c, cx, base - bh - ch - 1, max(2, (2 * r) // 3))


def _scroll(c, cx, cy, r):            # Scripts — a scroll with rolled ends
    # Two thin rolls with a written sheet between. The lines of writing are short
    # and RAGGED (the last one is stubby) — even-length full-width rules read as
    # slats, and the whole icon turned into a window blind.
    w = 2 * r - 3
    x = cx - w // 2
    top, bot = cy - r + 1, cy + r - 3
    _rbox(c, x, top, w, 3)                       # top roll
    _rbox(c, x, bot, w, 3)                       # bottom roll
    c.vline(x + 1, top + 3, bot - top - 3, 1)    # the sheet
    c.vline(x + w - 2, top + 3, bot - top - 3, 1)
    inner = bot - top - 4
    n = min(3, max(1, inner // 5))
    for i in range(n):
        yy = top + 6 + i * (inner // n if n else 4)
        if yy < bot - 1:
            ln = w - 6 if i < n - 1 else (w - 6) // 2
            c.hline(x + 3, yy, max(2, ln), 1)


def _medkit(c, cx, cy, r):            # Repair — a med kit (cross on a case)
    # Distinct from the Tools wrench, and every part is derived from r so the
    # cross stays centred and square when the icon shrinks.
    w, h = 2 * r, 2 * r - 2
    x, y = cx - r, cy - r + 1
    _rbox(c, x, y, w, h)
    hw = max(2, r // 2)                                  # handle on the lid
    c.hline(cx - hw // 2, y - 1, hw, 1)
    t = max(1, r // 3)                                   # cross bar thickness
    a = max(3, r)                                        # cross arm span
    c.fill_rect(cx - t // 2, cy - a // 2, t, a, 1)
    c.fill_rect(cx - a // 2, cy - t // 2, a, t, 1)


def _uarc(c, cx, cy, rr):
    """Upper semicircle (Bresenham). Used for the WiFi/LoRa arcs — sampling a
    circle equation per-column left gaps that turned to dust at neighbour size."""
    x, y, d = 0, rr, 1 - rr
    while x <= y:
        for a, b in ((x, y), (y, x)):
            c.pixel(cx + a, cy - b, 1)
            c.pixel(cx - a, cy - b, 1)
        if d < 0:
            d += 2 * x + 3
        else:
            d += 2 * (x - y) + 5
            y -= 1
        x += 1


def _kbd(c, cx, cy, r):               # Keyboard — a case with keys and a space bar
    w, h = 2 * r, max(6, int(1.3 * r))
    x, y = cx - r, cy - h // 2
    _rbox(c, x, y, w, h)
    step = max(2, (w - 4) // 4)
    rows = 2 if h < 12 else 3
    for row in range(rows):
        yy = y + 2 + row * max(2, (h - 5) // rows)
        if yy >= y + h - 3:
            break
        for i in range(4):
            xx = x + 2 + i * step
            if xx < x + w - 2:
                c.hline(xx, yy, max(1, step - 1), 1)
    c.hline(x + 3, y + h - 3, w - 6, 1)                      # space bar


def _radar(c, cx, cy, r):             # Radar — a scope with a sweep and a blip
    # A round scope, not more arcs: at neighbour size the arc version was
    # indistinguishable from the WiFi and LoRa icons, which sit next to it.
    c.circle(cx, cy, r - 1, 1)
    c.circle(cx, cy, max(2, (r - 1) // 2), 1)
    c.pixel(cx, cy, 1)
    e = r - 2
    c.line(cx, cy, cx + e, cy - e, 1)                    # the sweep arm
    c.line(cx, cy, cx + e - 1, cy - e, 1)
    c.fill_circle(cx - max(2, r // 3), cy + max(2, r // 3), max(1, r // 4), 1)


def _person(c, cx, cy, r):            # Presence — a figure in a doorway
    _rbox(c, cx - r, cy - r, 2 * r, 2 * r)                      # the doorway
    head = max(1, r // 4)
    c.circle(cx, cy - r // 2, head, 1)
    c.vline(cx, cy - r // 2 + head, r // 2 + 2, 1)               # body
    c.line(cx, cy, cx - head - 1, cy + r // 3, 1)                # arms
    c.line(cx, cy, cx + head + 1, cy + r // 3, 1)
    c.line(cx, cy + r // 2, cx - head - 1, cy + r - 2, 1)        # legs
    c.line(cx, cy + r // 2, cx + head + 1, cy + r - 2, 1)


_MAP = {
    'dht11': _thermo, 'gps': _pin, 'pn532': _nfc, 'cc1101': _radio,
    'sx1276': _antenna, 'bt': _bt, 'ibutton': _key, 'sdcard': _sd,
    'battery': _battery, 'buzzer': _speaker, 'vibration': _vibe, 'led': _led,
    'wifi': _wifi, 'scripts': _scroll, 'settings': _gear, 'logs': _doc,
    'tools': _wrench, 'check': _check, 'msg': _chat, 'power': _power,
    'notes': _notes, 'clock': _clock, 'fix': _medkit, 'cmds': _terminal,
    'kbd': _kbd, 'store': _store, 'diag': _stethoscope,
    'wardrive': _wardrive, 'radar': _radar,
    'presence': _person,
}


def draw(c, key, cx, cy, r, label=''):
    try:
        if key in ('ir', 'ir_rx'):
            return _remote(c, cx, cy, r, False)
        if key == 'ir_tx':
            return _remote(c, cx, cy, r, True)
        fn = _MAP.get(key)
        if fn is not None:
            return fn(c, cx, cy, r)
    except Exception:
        pass
    # generic: box + the first letter (also the fallback if a draw fn errors)
    c.rect(cx - r, cy - r, 2 * r, 2 * r, 1)
    ch = (label[:1] or key[:1] or '?').upper()
    sc = 2 if r >= 9 else 1
    import novafont5x7 as _f
    c.char(cx - (_f.WIDTH * sc) // 2, cy - (_f.HEIGHT * sc) // 2, ord(ch), 1, sc)
