# Generates novafont5x7.py — the compact 5x7 UI font — from petabyt/font's font.h
# (Daniel C., MIT licence). That file stores each glyph as ASCII art ('#' = lit,
# space = clear, 7 rows x 5 cols), which converts deterministically, so there is no
# guessing about bit order.
#
# Output layout matches novafont.py so both fonts are drop-in for the canvas:
# column-packed, one byte per column, bit (1 << row) = pixel, row 0 at the top.
#
#   python3 genfont5x7.py path/to/font.h
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT = os.path.normpath(os.path.join(_HERE, '..', '..', 'packages', 'novad1',
                                     'novafont5x7.py'))

FIRST, LAST = 0x20, 0x7e
W, H = 5, 7


# petabyt/font omits these 8; drawn here in the same 5x7 grid so the set is
# complete (they show up in paths, pipes, emails and shell text).
EXTRA = {
    '$': ["..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."],
    '&': [".##..", "#..#.", "#.#..", ".#...", "#.#.#", "#..#.", ".##.#"],
    '@': [".###.", "#...#", "#.##.", "#.#.#", "#.##.", "#....", ".###."],
    '[': ["..##.", "..#..", "..#..", "..#..", "..#..", "..#..", "..##."],
    '\\': ["#....", "#....", ".#...", "..#..", "...#.", "....#", "....#"],
    ']': [".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".##.."],
    '^': ["..#..", ".#.#.", "#...#", ".....", ".....", ".....", "....."],
    '|': ["..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
}


def parse(text):
    """{char: [7 strings of 5 chars]} from the font[] table."""
    glyphs = {}
    # {'A', { "row", ... }}  — the letter may be a normal char or an escape.
    for m in re.finditer(r"\{\s*'((?:\\.|[^'\\])+)'\s*,\s*\{(.*?)\}\s*\}", text, re.S):
        lit, body = m.group(1), m.group(2)
        ch = {"\\'": "'", '\\\\': '\\', '\\"': '"'}.get(lit, lit)
        if len(ch) != 1:
            continue
        rows = re.findall(r'"([^"]*)"', body)
        if len(rows) < H:
            continue
        glyphs[ch] = [(r + ' ' * W)[:W] for r in rows[:H]]
    return glyphs


def pack(rows):
    """ASCII-art rows -> W column bytes, bit (1<<row) set for a lit pixel.

    The glyph is CENTRED in its cell first. The source draws narrow characters
    (i . ! : l) hard against the left edge, which in a monospaced cell makes them
    look shoved left of everything else — centring here bakes the fix into the data
    so there's no per-draw cost and the mock matches the device exactly."""
    cols = []
    for x in range(W):
        b = 0
        for y in range(H):
            if rows[y][x] not in (' ', '\t', '.'):   # '.' = clear in EXTRA art
                b |= (1 << y)
        cols.append(b)
    lit = [i for i, b in enumerate(cols) if b]
    if lit:
        lo, hi = lit[0], lit[-1] + 1
        shift = (W - (hi - lo)) // 2 - lo
        if shift > 0:
            cols = [0] * shift + cols[:W - shift]
        elif shift < 0:
            cols = cols[-shift:] + [0] * (-shift)
    return cols


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: genfont5x7.py path/to/font.h')
    glyphs = parse(open(sys.argv[1], encoding='utf-8', errors='replace').read())
    for _c, _rows in EXTRA.items():          # fill the 8 the source omits
        glyphs.setdefault(_c, _rows)
    if not glyphs:
        raise SystemExit('no glyphs parsed — is that petabyt/font font.h?')

    data = bytearray()
    missing = []
    for code in range(FIRST, LAST + 1):
        ch = chr(code)
        rows = glyphs.get(ch)
        if rows is None:
            missing.append(ch)
            rows = [' ' * W] * H          # blank rather than a wrong glyph
        data.extend(pack(rows))

    L = []
    L.append('# Desc: Nova D1 compact UI font — 5x7 (petabyt/font, Daniel C., MIT).')
    L.append('# File: /Packages/NovaD1/novafont5x7.py')
    L.append('#')
    L.append('# Same column-packed layout as novafont: WIDTH bytes per glyph, byte =')
    L.append('# one column, bit (1<<row) = a pixel, row 0 = top. Smaller than the 8x8')
    L.append('# face so more rows/characters fit the 128x64 panel.')
    L.append('# Regenerate: repo/tools/novad1/genfont5x7.py <font.h>')
    L.append('')
    L.append('FIRST = 0x%02x' % FIRST)
    L.append('WIDTH = %d' % W)
    L.append('HEIGHT = %d' % H)
    L.append('ADVANCE = %d' % (W + 1))
    L.append('')
    hexs = ''.join('\\x%02x' % b for b in data)
    chunk = 24 * 4
    L.append('DATA = (')
    for i in range(0, len(hexs), chunk):
        L.append("    b'%s'" % hexs[i:i + chunk])
    L.append(')')
    L.append('')
    open(_OUT, 'w').write('\n'.join(L))
    print('wrote {}  ({} glyphs, {} bytes)'.format(
        os.path.normpath(_OUT), (LAST - FIRST + 1), len(data)))
    if missing:
        print('  blanks (not in source): ' + ''.join(missing))


if __name__ == '__main__':
    main()
