import re
T='./out/'
txt=open(T+'font8x8.h').read()
vals=[int(x,16) for x in re.findall(r'0x[0-9A-Fa-f]{2}',txt)]
FIRST,LAST=0x20,0x7e; H=8; W=8
# transpose row-packed (LSB=left) -> column-packed (bit r = row r, bit0=top)
glyphs={}
maxcol=0
for code in range(FIRST,LAST+1):
    rows=vals[code*8:code*8+8]
    cols=[]
    for c in range(W):
        col=0
        for r in range(H):
            if rows[r]&(1<<c): col|=(1<<r)
        cols.append(col)
        if col and code!=0x20: maxcol=max(maxcol,c)
    glyphs[code]=cols
ADV=8  # font8x8 native cell width
data=bytearray()
for code in range(FIRST,LAST+1):
    for c in range(W):
        data.append(glyphs[code][c])
print('maxcol',maxcol,'-> ADVANCE',ADV,'  glyphs',LAST-FIRST+1,'  data',len(data))
L=[]
L.append('# Desc: Nova D1 shared bitmap font — font8x8 (IBM BIOS 8x8, public domain).')
L.append('# File: /Packages/NovaD1/novafont.py')
L.append('#')
L.append('# The classic, battle-tested 8x8 terminal font (dhepper/font8x8, public')
L.append('# domain), transposed to column-packed 1-bit: each glyph = WIDTH bytes, byte')
L.append('# = one column, bit (1<<row) = a pixel (row 0 = top). Matches the MONO_VLSB')
L.append('# canvas so device == PC mock. Regenerate: repo/tools/novad1/genfont.py.')
L.append('')
L.append('FIRST = 0x%02x'%FIRST)
L.append('WIDTH = %d'%W)
L.append('HEIGHT = %d'%H)
L.append('ADVANCE = %d'%ADV)
L.append('')
hexs=''.join('\\x%02x'%v for v in data)
chunk=24*4
L.append('DATA = (')
for i in range(0,len(hexs),chunk):
    L.append("    b'%s'"%hexs[i:i+chunk])
L.append(')')
L.append('')
open('RPCortex-repo/repo/packages/novad1/novafont.py','w').write('\n'.join(L))
cp=open('RPCortex-repo/repo/tools/novad1/genfont.py','w'); cp.write(open(__file__).read()); cp.close()
print('wrote novafont.py (font8x8)')
