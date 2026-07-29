# display: the OLED backends. Verifies each panel's init sequence and that the
# page-diff push only rewrites pages that actually changed. A wrong init sequence
# fails SILENTLY on real hardware (blank or garbled panel, no exception), so the
# byte-level assertions here are the only cheap guard there is.
import sys
import _shims
_shims.install()
from _shims import T
import display
import novacanvas

t = T('test_display')

_CMD, _DAT = 0x00, 0x40


class FakeI2C:
    """Records every write so the init stream and the page pushes can be inspected."""
    def __init__(self, found=None):
        self.writes = []
        self._found = found if found is not None else [0x3c]

    def scan(self):
        return self._found

    def writeto(self, addr, buf):
        self.writes.append((addr, bytes(buf)))

    def cmds(self):
        """Command bytes, in order."""
        return [w[1][1] for w in self.writes if w[1] and w[1][0] == _CMD]

    def data(self):
        return [w[1][1:] for w in self.writes if w[1] and w[1][0] == _DAT]


# ------------------------------------------------------------------ factory
i2c = FakeI2C()
t.ok(isinstance(display.open_display(i2c, kind='sh1106'), display.SH1106), "kind='sh1106'")
t.ok(isinstance(display.open_display(i2c, kind='ssd1306'), display.SSD1306), "kind='ssd1306'")
t.ok(isinstance(display.open_display(i2c, kind='ssd1309'), display.SSD1309), "kind='ssd1309'")
t.ok(isinstance(display.open_display(i2c, kind='mock'), display.MockDisplay), "kind='mock'")
t.ok(isinstance(display.open_display(None, kind='auto'), display.MockDisplay),
     'no bus -> mock, so host tooling never needs hardware')
t.ok('ssd1309' in display.KINDS, 'ssd1309 is advertised in KINDS')

# The shipping panel must stay the auto default. Adding SSD1309 support must not
# change what an existing device picks when nothing is configured.
t.ok(isinstance(display.open_display(i2c, kind='auto'), display.SH1106),
     'auto still resolves to SH1106 (the shipping panel), not the new backend')
alt = display.open_display(FakeI2C(found=[0x3d]), kind='auto')
t.eq(alt.addr, 0x3d, 'auto still falls back to the 0x3d address when 0x3c is absent')

# ------------------------------------------------- SSD1309 init, the risky part
bus = FakeI2C()
d = display.SSD1309(bus, 0x3c, 128, 64)
c = bus.cmds()
t.eq(c[:2], [0xfd, 0x12], 'command unlock is FIRST — the panel ignores all else until then')
t.ok(0x8d not in c, 'no SSD1306 charge-pump command (SSD1309 uses an external boost)')
t.ok(0xae in c and c[-1] == 0xaf, 'display off during setup, on at the end')
t.eq(c[c.index(0xa8) + 1], 0x3f, 'multiplex ratio set for 64 rows')
t.eq(c[c.index(0xda) + 1], 0x12, 'COM pins set to the alternative 128x64 config')

# show() writes page-at-a-time, so the addressing mode must be PAGE (0x02). Stock
# SSD1309 drivers use horizontal (0x00), which would render garbage through show().
t.eq(c[c.index(0x20) + 1], 0x02, 'PAGE addressing mode, matching the page-diff show()')
t.eq(display.SSD1309._col_offset, 0, 'no column offset: 128-column controller')
t.eq(display.SSD1306._col_offset, 0, 'SSD1306 unchanged')
t.eq(display.SH1106._col_offset, 2, 'SH1106 keeps its +2 offset (132-column part)')

# ------------------------------------------------------- page-diff push behaviour
cv = novacanvas.Canvas(128, 64)
bus = FakeI2C()
d = display.SSD1309(bus, 0x3c, 128, 64)

bus.writes = []
d.show(cv)
t.eq(len(bus.data()), 8, 'first push writes all 8 pages')

bus.writes = []
d.show(cv)
t.eq(len(bus.data()), 0, 'an unchanged frame writes nothing at all')

cv.pixel(0, 0, 1)                       # page 0 only
bus.writes = []
d.show(cv)
t.eq(len(bus.data()), 1, 'a one-page change pushes exactly one page')
t.eq(bus.cmds()[0], 0xb0 | 0, 'and addresses page 0')

cv.pixel(5, 40, 1)                      # row 40 -> page 5
bus.writes = []
d.show(cv)
t.eq(bus.cmds()[0], 0xb0 | 5, 'a change on row 40 addresses page 5')

bus.writes = []
d.invalidate()
d.show(cv)
t.eq(len(bus.data()), 8, 'invalidate() forces a full push again')

bus.writes = []
d.power(False)
d.show(cv)
t.eq(len(bus.data()), 8, 'a power change also forces a full push (panel state was lost)')

# The column offset has to reach the wire, or an SH1106 renders shifted by 2px.
bus = FakeI2C()
sh = display.SH1106(bus, 0x3c, 128, 64)
bus.writes = []
sh.show(novacanvas.Canvas(128, 64))
c = bus.cmds()
t.eq(c[1], 0x00 | 2, 'SH1106 sends the low column nibble with its +2 offset')
t.eq(c[2], 0x10 | 0, 'and the high column nibble')

sys.exit(t.done())
