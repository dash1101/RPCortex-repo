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


def _thermo(c, cx, cy, r):            # DHT11 — thermometer
    c.fill_circle(cx, cy + r - 2, max(2, r // 2), 1)
    c.vline(cx, cy - r, r, 1)
    c.vline(cx - 1, cy - r, r, 1)
    for i in range(2):
        c.hline(cx + 1, cy - r + 2 + i * 3, max(2, r // 3), 1)


def _pin(c, cx, cy, r):               # GPS — map pin
    c.circle(cx, cy - r // 3, r - r // 3, 1)
    c.pixel(cx, cy - r // 3, 1)
    c.line(cx - (r - r // 3), cy - r // 3 + 1, cx, cy + r, 1)
    c.line(cx + (r - r // 3), cy - r // 3 + 1, cx, cy + r, 1)


def _nfc(c, cx, cy, r):               # NFC/PN532 — card + contactless waves
    c.rect(cx - r, cy - r // 2, r + 2, r, 1)
    for i in range(3):
        c.line(cx + 2 + i * 3, cy - r // 2, cx + 2 + i * 3, cy + r // 2, 1)


def _radio(c, cx, cy, r):             # Sub-GHz/CC1101 — mast + waves
    c.vline(cx, cy - r // 2, r + r // 2, 1)
    c.fill_circle(cx, cy - r // 2, 1, 1)
    for i in range(1, 3):
        c.line(cx - i * 3, cy - r, cx - i * 2, cy, 1)
        c.line(cx + i * 3, cy - r, cx + i * 2, cy, 1)


def _antenna(c, cx, cy, r):           # LoRa/SX1276 — antenna radiating
    c.vline(cx, cy - r // 4, r, 1)
    c.fill_circle(cx, cy - r // 4, 1, 1)
    c.line(cx, cy - r // 4, cx - r, cy - r, 1)
    c.line(cx, cy - r // 4, cx + r, cy - r, 1)


def _bt(c, cx, cy, r):                # Bluetooth rune
    c.vline(cx, cy - r, 2 * r, 1)
    c.line(cx, cy - r, cx + r // 2, cy - r // 2, 1)
    c.line(cx + r // 2, cy - r // 2, cx, cy, 1)
    c.line(cx, cy, cx + r // 2, cy + r // 2, 1)
    c.line(cx + r // 2, cy + r // 2, cx, cy + r, 1)
    c.line(cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2, 1)
    c.line(cx - r // 2, cy + r // 2, cx + r // 2, cy - r // 2, 1)


def _remote(c, cx, cy, r, up):        # IR — beam into/out of a sensor box
    c.rect(cx - r // 2, cy, r, r, 1)
    dy = -1 if up else 1
    for i in range(3):
        yy = cy + (dy * (i * 2 + 1))
        c.hline(cx - r + i, yy if up else cy - 1 - i, 2, 1)
    for i in range(3):
        base = cy - 1 if up else cy
        c.line(cx - r // 3 + i * (r // 3), base, cx - r // 3 + i * (r // 3),
               base - (r if up else -r), 1)


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
    c.rect(cx - r // 2, cy - r, r, 2 * r, 1)
    for i in range(2):
        c.vline(cx - r + i * 2, cy - r // 2, r, 1)
        c.vline(cx + r // 2 + 1 + i * 2, cy - r // 2, r, 1)


def _led(c, cx, cy, r):               # status LED — sun/glow
    c.fill_circle(cx, cy, max(2, r // 2), 1)
    for a in ((-r, 0), (r, 0), (0, -r), (0, r),
              (-r, -r), (r, r), (-r, r), (r, -r)):
        c.line(cx + a[0] // 2, cy + a[1] // 2, cx + a[0], cy + a[1], 1)


def _wifi(c, cx, cy, r):
    c.fill_circle(cx, cy + r - 1, 1, 1)
    for rr in range(r // 2, r + 1, max(1, r // 3)):
        for dx in range(-rr, rr + 1):
            dy2 = rr * rr - dx * dx
            if dy2 >= 0:
                c.pixel(cx + dx, cy + r - 1 - int(dy2 ** 0.5), 1)


def _doc(c, cx, cy, r):               # scripts — document
    c.rect(cx - r // 2, cy - r, r, 2 * r, 1)
    for i in range(3):
        c.hline(cx - r // 2 + 2, cy - r // 2 + i * 3, r - 4, 1)


def _gear(c, cx, cy, r):              # settings
    c.circle(cx, cy, r - 2, 1)
    c.fill_circle(cx, cy, max(1, r // 3), 0)
    c.circle(cx, cy, max(1, r // 3), 1)
    for a in ((0, -r), (0, r), (-r, 0), (r, 0)):
        c.line(cx + (a[0] * 2) // 3, cy + (a[1] * 2) // 3, cx + a[0], cy + a[1], 1)


def _check(c, cx, cy, r):             # System Check — clipboard + tick
    c.rect(cx - r + 1, cy - r, 2 * r - 2, 2 * r, 1)
    c.fill_rect(cx - 3, cy - r - 2, 6, 3, 1)         # clip
    c.line(cx - r + 3, cy + 1, cx - 1, cy + r - 3, 1)  # check mark
    c.line(cx - 1, cy + r - 3, cx + r - 3, cy - r + 4, 1)


def _chat(c, cx, cy, r):              # Messages — speech bubble
    c.rect(cx - r, cy - r, 2 * r, int(1.4 * r), 1)
    c.line(cx - r // 2, cy - r + int(1.4 * r), cx - r // 3, cy + r, 1)
    c.line(cx - r // 3, cy + r, cx, cy - r + int(1.4 * r), 1)
    for i in range(3):
        c.pixel(cx - r // 2 + i * (r // 2), cy - r // 3, 1)


def _power(c, cx, cy, r):             # power symbol (ring + break + stem)
    c.circle(cx, cy, r - 1, 1)
    c.fill_rect(cx - 2, cy - r - 1, 5, 4, 0)
    c.vline(cx, cy - r - 1, r + 2, 1)


def _notes(c, cx, cy, r):             # Notifications — bell
    c.line(cx - r + 1, cy + r - 2, cx, cy - r, 1)
    c.line(cx + r - 1, cy + r - 2, cx, cy - r, 1)
    c.hline(cx - r + 1, cy + r - 2, 2 * r - 2, 1)
    c.fill_circle(cx, cy + r - 1, 1, 1)
    c.fill_circle(cx, cy - r, 1, 1)


def _clock(c, cx, cy, r):             # Clock — dial + hands
    c.circle(cx, cy, r - 1, 1)
    c.line(cx, cy, cx, cy - (r - 4), 1)          # hour hand (up)
    c.line(cx, cy, cx + (r - 3), cy, 1)          # minute hand (right)
    c.pixel(cx, cy, 1)


def _wrench(c, cx, cy, r):            # Troubleshoot — wrench
    # open jaws top-left, shaft running to bottom-right
    c.line(cx - r + 2, cy - r + 3, cx + r - 3, cy + r - 2, 1)
    c.line(cx - r + 3, cy - r + 2, cx + r - 2, cy + r - 3, 1)
    c.circle(cx - r + 4, cy - r + 4, 3, 1)
    c.fill_rect(cx - r + 2, cy - r + 1, 3, 2, 0)  # knock the jaw opening out


def _terminal(c, cx, cy, r):          # Commands — a terminal window with a prompt
    c.rect(cx - r, cy - r + 1, 2 * r, 2 * r - 2, 1)
    c.hline(cx - r, cy - r + 4, 2 * r, 1)         # title bar
    c.line(cx - r + 3, cy - 1, cx - r + 6, cy + 2, 1)   # '>' chevron
    c.line(cx - r + 6, cy + 2, cx - r + 3, cy + 5, 1)
    c.hline(cx - r + 8, cy + 5, max(2, r - 2), 1)       # cursor line


def _store(c, cx, cy, r):             # App Store — a shopping bag
    c.rect(cx - r + 2, cy - r + 4, 2 * r - 4, 2 * r - 6, 1)
    c.line(cx - r + 5, cy - r + 4, cx - r + 5, cy - r + 1, 1)   # handle
    c.line(cx + r - 6, cy - r + 4, cx + r - 6, cy - r + 1, 1)
    c.hline(cx - r + 5, cy - r + 1, (r - 4) if r > 5 else 2, 1)


def _stethoscope(c, cx, cy, r):       # Diagnostics — pulse/heartbeat trace
    c.rect(cx - r, cy - r + 2, 2 * r, 2 * r - 4, 1)
    y = cy
    c.hline(cx - r + 2, y, 3, 1)
    c.line(cx - r + 5, y, cx - r + 7, y - 4, 1)   # spike up
    c.line(cx - r + 7, y - 4, cx - r + 9, y + 4, 1)
    c.line(cx - r + 9, y + 4, cx - r + 11, y, 1)
    c.hline(cx - r + 11, y, max(2, r - 4), 1)


def _wardrive(c, cx, cy, r):          # Wardrive — a car below broadcast waves
    # car: body + cabin + wheels, sitting on the lower half
    by = cy + 3
    c.fill_rect(cx - r + 2, by, 2 * r - 4, 3, 1)
    c.fill_rect(cx - r + 5, by - 3, r + 1, 3, 1)
    c.pixel(cx - r + 4, by + 4, 1)
    c.pixel(cx + r - 5, by + 4, 1)
    c.hline(cx - r + 3, by + 4, 2, 1)
    c.hline(cx + r - 6, by + 4, 2, 1)
    # two broadcast chevrons above (drawn as lines, not knocked-out circles —
    # the knockout approach erased the car)
    for k, w in ((0, 4), (3, 7)):
        ty = cy - 6 + k
        c.line(cx - w, ty + w // 2, cx, ty, 1)
        c.line(cx, ty, cx + w, ty + w // 2, 1)


_MAP = {
    'dht11': _thermo, 'gps': _pin, 'pn532': _nfc, 'cc1101': _radio,
    'sx1276': _antenna, 'bt': _bt, 'ibutton': _key, 'sdcard': _sd,
    'battery': _battery, 'buzzer': _speaker, 'vibration': _vibe, 'led': _led,
    'wifi': _wifi, 'scripts': _doc, 'settings': _gear, 'logs': _doc,
    'check': _check, 'msg': _chat, 'power': _power, 'notes': _notes,
    'clock': _clock, 'fix': _wrench, 'cmds': _terminal, 'store': _store,
    'diag': _stethoscope, 'wardrive': _wardrive,
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
    import novafont as _f
    c.char(cx - (_f.WIDTH * sc) // 2, cy - (_f.HEIGHT * sc) // 2, ord(ch), 1, sc)
