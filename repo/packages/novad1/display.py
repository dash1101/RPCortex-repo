# Desc: Nova D1 display layer — modular OLED backends behind one interface.
# File: /Packages/NovaD1/display.py
#
# A backend takes a novacanvas.Canvas and pushes its MONO_VLSB buffer to the
# panel. Backends: SH1106 (primary), SSD1306, and Mock (host-only -> PNG, for the
# no-hardware concept render). open_display() auto-detects on I2C; the UI never
# cares which panel it is. SH1106's +2 column offset lives HERE, not in the UI.
#
# MicroPython-safe: no f-strings, positional split, .format() only.

_CMD = 0x00     # I2C control byte: command stream
_DAT = 0x40     # I2C control byte: data stream


class _OledI2C:
    """Shared I2C OLED base — subclasses set _init_cmds and _col_offset."""
    _init_cmds = ()
    _col_offset = 0

    def __init__(self, i2c, addr=0x3c, w=128, h=64):
        self.i2c = i2c
        self.addr = addr
        self.w = w
        self.h = h
        self.pages = h // 8
        self._last = None               # previous frame, for page-diff pushes
        self._cmd(self._init_cmds)

    def _cmd(self, cmds):
        for c in cmds:
            self.i2c.writeto(self.addr, bytes((_CMD, c)))

    def contrast(self, value):
        self._cmd((0x81, value & 0xff))

    def power(self, on):
        self._cmd((0xaf if on else 0xae,))
        self._last = None               # panel state changed -> force a full push

    def invert(self, on):
        self._cmd((0xa7 if on else 0xa6,))

    def invalidate(self):
        self._last = None               # force the next show() to push every page

    def show(self, canvas):
        # Page-diff: only push the 128-byte pages that actually CHANGED since the
        # last frame. A full 8-page (~1 KB) I2C write is the biggest synchronous
        # block on the shared event loop; most UI updates touch 1-2 pages, so this
        # cuts that block ~4-8x and keeps the shell/animation responsive.
        off = self._col_offset
        buf = canvas.buf
        w = self.w
        last = self._last
        for page in range(self.pages):
            start = page * w
            end = start + w
            if last is not None and last[start:end] == buf[start:end]:
                continue                # unchanged page -> skip the I2C write
            self._cmd((0xb0 | page,             # set page
                       0x00 | (off & 0x0f),     # lower column nibble
                       0x10 | (off >> 4)))       # higher column nibble
            self.i2c.writeto(self.addr, bytes((_DAT,)) + bytes(buf[start:end]))
        self._last = bytes(buf)         # snapshot for the next diff


class SH1106(_OledI2C):
    # SH1106 is a 132-col controller showing 128 -> +2 column offset. Page-mode.
    _col_offset = 2
    _init_cmds = (0xae, 0xd5, 0x80, 0xa8, 0x3f, 0xd3, 0x00, 0x40,
                  0xad, 0x8b, 0xa1, 0xc8, 0xda, 0x12, 0x81, 0x80,
                  0xd9, 0x22, 0xdb, 0x35, 0xa4, 0xa6, 0xaf)


class SSD1306(_OledI2C):
    _col_offset = 0
    _init_cmds = (0xae, 0xd5, 0x80, 0xa8, 0x3f, 0xd3, 0x00, 0x40,
                  0x8d, 0x14, 0x20, 0x02, 0xa1, 0xc8, 0xda, 0x12,
                  0x81, 0xcf, 0xd9, 0xf1, 0xdb, 0x40, 0xa4, 0xa6, 0xaf)


class SSD1309(_OledI2C):
    # DEVICE-UNCONFIRMED: this sequence is grounded in a working SSD1309 driver and the
    # host tests assert its byte-level shape, but no SSD1309 panel has been attached
    # yet. A wrong OLED init fails SILENTLY — blank or garbled, no exception — so this
    # is not verified until a real panel lights up.
    #
    # For the 2.42" 128x64 panel. Same 128-column geometry as the SSD1306 (so no
    # column offset, unlike the SH1106), but two init differences that matter and
    # fail silently — a wrong sequence gives a blank panel with no error:
    #
    #   0xfd 0x12  COMMAND UNLOCK. The SSD1309 powers up with its command
    #              interface locked and ignores everything until unlocked, so this
    #              MUST come first.
    #   no 0x8d    The SSD1306's charge-pump enable does not exist here; the
    #              SSD1309 drives the panel from an external boost converter.
    #
    # Everything else follows the standard 128x64 setup. One deliberate deviation
    # from stock SSD1309 drivers: they set 0x20 0x00 (horizontal addressing), but
    # _OledI2C.show() writes page-at-a-time for the page-diff optimisation, so this
    # uses 0x20 0x02 (page addressing) to match — same choice the SSD1306 makes.
    _col_offset = 0
    _init_cmds = (0xfd, 0x12,              # unlock the command interface first
                  0xae,                    # display off while we configure
                  0xd5, 0x80,              # clock divide / oscillator
                  0xa8, 0x3f,              # multiplex ratio = 64 rows
                  0xd3, 0x00,              # no vertical offset
                  0x40,                    # start line 0
                  0x20, 0x02,              # PAGE addressing (see note above)
                  0xa1,                    # segment re-map: col 127 -> SEG0
                  0xc8,                    # COM scan direction remapped
                  0xda, 0x12,              # COM pins: alternative, for 128x64
                  0x81, 0xcf,              # contrast
                  0xd9, 0xf1,              # pre-charge period
                  0xdb, 0x30,              # VCOMH deselect ~0.83 x VCC
                  0xa4,                    # resume from GDDRAM
                  0xa6,                    # normal, not inverted
                  0x2e,                    # deactivate scroll
                  0xaf)                    # display on


class MockDisplay:
    """Host-only backend: keeps the last buffer; render_png() draws an OLED-look
    PNG (lazy-imports Pillow). Never used on-device."""
    _col_offset = 0

    def __init__(self, w=128, h=64):
        self.w = w
        self.h = h
        self.pages = h // 8
        self.last = None

    def contrast(self, value):
        pass

    def power(self, on):
        pass

    def invert(self, on):
        pass

    def show(self, canvas):
        self.last = bytes(canvas.buf)

    def render_png(self, path, scale=5, on=(150, 225, 255), off=(7, 11, 22),
                   border=10, label=None):
        from PIL import Image, ImageDraw
        buf = self.last
        iw = self.w * scale + border * 2
        ih = self.h * scale + border * 2 + (16 if label else 0)
        img = Image.new('RGB', (iw, ih), (2, 4, 10))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([border - 4, border - 4,
                             iw - border + 4, border + self.h * scale + 4],
                            radius=8, fill=off, outline=(40, 60, 90))
        for y in range(self.h):
            for x in range(self.w):
                idx = (y >> 3) * self.w + x
                if buf and (buf[idx] & (1 << (y & 7))):
                    px = border + x * scale
                    py = border + y * scale
                    d.rectangle([px, py, px + scale - 2, py + scale - 2], fill=on)
        if label:
            d.text((border, ih - 14), label, fill=(120, 140, 170))
        img.save(path)
        return path


KINDS = ('sh1106', 'ssd1306', 'ssd1309', 'mock')


def open_display(i2c=None, kind='auto', addr=0x3c, w=128, h=64):
    """Factory. On-device: probe I2C and open the panel. Off-device or kind='mock':
    return MockDisplay. kind forces 'sh1106' / 'ssd1306' / 'ssd1309' / 'mock'."""
    if kind == 'mock' or i2c is None:
        return MockDisplay(w, h)
    if kind == 'sh1106':
        return SH1106(i2c, addr, w, h)
    if kind == 'ssd1306':
        return SSD1306(i2c, addr, w, h)
    if kind == 'ssd1309':
        return SSD1309(i2c, addr, w, h)
    # auto: these panels share an I2C address and cannot be told apart reliably, so
    # auto stays SH1106 — the shipping panel. Selecting SSD1306/SSD1309 is a config
    # choice (Apps.NovaD1_Display), never a guess.
    try:
        found = i2c.scan()
    except Exception:
        found = []
    if addr not in found and (0x3d in found):
        addr = 0x3d
    return SH1106(i2c, addr, w, h)
