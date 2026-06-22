# Generate a compact 5x7 bitmap font (ASCII 0x20-0x7E) for the Nova D1 UI.
# Column-packed: per glyph, `width` bytes; byte = a column, bit i = row i (top=0).
# Shared by device + mock so the PNG mock is pixel-true to the panel.
from PIL import Image, ImageDraw, ImageFont
import os

W, H, ADV = 5, 7, 6          # 5x7 glyph, 6px advance
FIRST, LAST = 0x20, 0x7e
paths = ['/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf']
font = None
for sz in (8, 9, 7):
    for p in paths:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, sz); FSZ=sz; FP=p; break
            except Exception: pass
    if font: break
if font is None:
    font = ImageFont.load_default(); FSZ='default'; FP='default'
print('font:', FP, FSZ)

data = bytearray()
for code in range(FIRST, LAST + 1):
    ch = chr(code)
    # render large, then threshold into the WxH cell
    img = Image.new('L', (16, 16), 0)
    d = ImageDraw.Draw(img); d.text((1, -1), ch, fill=255, font=font)
    px = img.load()
    # pack columns
    for c in range(W):
        col = 0
        for r in range(H):
            # sample with slight scaling: map cell (c,r) to render space
            sx, sy = c + 1, r + 1
            if px[sx, sy] > 110:
                col |= (1 << r)
        data.append(col)

# write novafont.py
out = ('# Desc: Nova D1 UI bitmap font — 5x7, ASCII 0x20-0x7E, column-packed.\n'
       '# byte = one column, bit i = row i (top=0). Shared by device + mock.\n'
       '# Auto-generated (tools/genfont). Do not hand-edit.\n'
       'FIRST = 0x20\nWIDTH = %d\nHEIGHT = %d\nADVANCE = %d\n' % (W, H, ADV))
out += 'DATA = ' + repr(bytes(data)) + '\n'
open('RPCortex-repo/repo/packages/novad1/novafont.py', 'w').write(out)
print('wrote novafont.py:', len(data), 'bytes,', (LAST-FIRST+1), 'glyphs')

# preview render
prev = Image.new('RGB', (ADV*22*4, H*4*3), (8,12,24))
pd = ImageDraw.Draw(prev)
def putc(ox, oy, code):
    gi = code - FIRST
    for c in range(W):
        b = data[gi*W + c]
        for r in range(H):
            if b & (1<<r):
                pd.rectangle([ (ox+c)*4, (oy+r)*4, (ox+c)*4+3, (oy+r)*4+3 ], fill=(120,220,255))
s1='ABCDEFGHIJKLMNOPQRSTU'; s2='abcdefghijklmnopqrstu'; s3='012345 :.-/% Nova D1!'
for i,ch in enumerate(s1): putc(i*ADV, 0, ord(ch))
for i,ch in enumerate(s2): putc(i*ADV, H+1, ord(ch))
for i,ch in enumerate(s3): putc(i*ADV, 2*(H+1), ord(ch))
prev.save('./out/font_preview.png')
print('preview saved')
