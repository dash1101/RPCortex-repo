#!/usr/bin/env python3
"""Rasterise a pixel-art SVG into a packed 1-bit bitmap for novaicons.

Written for pixelarticons (https://github.com/halfmage/pixelarticons, MIT,
(c) 2019 Gerrit Halfmann). Those icons are drawn on a 24x24 grid entirely from
axis-aligned rectangles expressed in SVG path shorthand, e.g.

    M9 0h6v2H9z    ->  move to (9,0), across 6, down 2, back to x=9, close
                       i.e. the rectangle (9, 0, 6, 2)

so they can be rasterised EXACTLY, pixel for pixel, with no anti-aliasing and no
rendering library. That is the whole reason to use pixel art here: a traced or
downsampled vector icon looks muddy on a 1-bit panel, whereas this is the artwork
as drawn.

Usage:
    python3 gensvgicon.py settings-cog.svg gear
"""
import re
import sys


def rects(svg):
    """Every rectangle in the file, as (x, y, w, h).

    Two things this has to get right, both of which produced silently wrong art
    on the first attempt:

    * `<defs>` / `<clipPath>` are STRIPPED first. pixelarticons wrap their icons
      in a clip path whose rect is the full 24x24 canvas — parse that as artwork
      and every icon comes out as a solid square.
    * Subpaths after the first use RELATIVE `m`, continuing from the previous
      point. Treating them as absolute (or skipping them) loses most of the
      drawing; this one file has 14 absolute and 19 relative subpaths.
    """
    svg = re.sub(r'<defs>.*?</defs>', '', svg, flags=re.S)
    out = []
    skipped = []
    for d in re.findall(r'\sd="([^"]+)"', svg):
        cx = cy = 0
        for sub in re.findall(r'[Mm][^Mm]*', d):
            m = re.match(r'([Mm])\s*(-?\d+)[ ,]?\s*(-?\d+)(.*)', sub.strip(), re.S)
            if not m:
                skipped.append(sub.strip())
                continue
            rel, ax, ay, rest = m.group(1) == 'm', int(m.group(2)), int(m.group(3)), m.group(4)
            if rel:
                cx += ax
                cy += ay
            else:
                cx, cy = ax, ay
            sx, sy = cx, cy
            minx = maxx = cx
            miny = maxy = cy
            for cmd, val in re.findall(r'([hvHVzZ])\s*(-?\d+)?', rest):
                if cmd in 'zZ':
                    continue
                if val == '':
                    continue
                v = int(val)
                if cmd == 'h':
                    cx += v
                elif cmd == 'H':
                    cx = v
                elif cmd == 'v':
                    cy += v
                elif cmd == 'V':
                    cy = v
                minx, maxx = min(minx, cx), max(maxx, cx)
                miny, maxy = min(miny, cy), max(maxy, cy)
            if maxx > minx and maxy > miny:
                out.append((minx, miny, maxx - minx, maxy - miny))
            else:
                skipped.append(sub.strip())
            cx, cy = sx, sy          # a closed subpath returns to its start
    return out, skipped


def raster(svg, size=24):
    grid = [[0] * size for _ in range(size)]
    rs, skipped = rects(svg)
    for x, y, w, h in rs:
        for yy in range(y, min(y + h, size)):
            for xx in range(x, min(x + w, size)):
                if 0 <= xx < size and 0 <= yy < size:
                    grid[yy][xx] = 1
    return grid, rs, skipped


def emit(name, grid, size=24):
    """Row-major, one integer per row (bit 0 = leftmost). 24 ints for a 24x24."""
    rows = []
    for y in range(size):
        v = 0
        for x in range(size):
            if grid[y][x]:
                v |= 1 << x
        rows.append(v)
    out = ['%s_W = %d' % (name.upper(), size), '%s = (' % name.upper()]
    for i in range(0, size, 4):
        out.append('    ' + ' '.join('0x%06X,' % r for r in rows[i:i + 4]))
    out.append(')')
    return '\n'.join(out)


def show(grid, size=24):
    return '\n'.join(''.join('##' if c else '..' for c in row) for row in grid)


if __name__ == '__main__':
    path = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else 'icon'
    svg = open(path).read()
    grid, rs, skipped = raster(svg)
    sys.stderr.write('%d rectangles, %d skipped\n' % (len(rs), len(skipped)))
    for s in skipped:
        sys.stderr.write('  SKIPPED: %s\n' % s[:70])
    sys.stderr.write(show(grid) + '\n')
    print(emit(name, grid))
