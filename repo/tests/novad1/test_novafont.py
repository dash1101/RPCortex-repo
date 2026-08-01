# The 5x7 UI font must be complete and correctly packed. A silently-wrong glyph
# renders as a solid block (or a blank) with no error — which is exactly what
# happened when the generator treated the '.' in hand-drawn art as a lit pixel and
# every added symbol became a filled square.
import sys
import _shims
_shims.install()
from _shims import T

import novafont5x7 as f

t = T('test_novafont')

data = b''.join(f.DATA) if isinstance(f.DATA, tuple) else f.DATA
n = 0x7e - 0x20 + 1

t.eq(f.WIDTH, 5, 'font is 5 wide')
t.eq(f.HEIGHT, 7, 'font is 7 tall')
t.eq(f.ADVANCE, 6, 'advance leaves a 1px gap')
t.eq(len(data), n * f.WIDTH, 'every printable ASCII glyph is present')


def cols(ch):
    i = (ord(ch) - f.FIRST) * f.WIDTH
    return data[i:i + f.WIDTH]


def ink(ch):
    return sum(bin(c).count('1') for c in cols(ch))


# No glyph may be a SOLID BLOCK — that's the signature of art parsed with the wrong
# 'clear' character, and it's unreadable on the panel.
solid = [chr(c) for c in range(f.FIRST, f.FIRST + n)
         if all(b == 0x7f for b in cols(chr(c)))]
t.ok(not solid, 'no glyph is a solid block: {}'.format(solid[:10]))

# Space is the only glyph allowed to be blank.
blank = [chr(c) for c in range(f.FIRST, f.FIRST + n) if ink(chr(c)) == 0]
t.eq(blank, [' '], 'only space is blank (blanks: {})'.format(blank[:10]))

# Nothing may use row 7+ (the face is 7 tall; a stray bit would bleed into the row
# below at a 9px pitch).
over = [chr(c) for c in range(f.FIRST, f.FIRST + n)
        if any(b >> f.HEIGHT for b in cols(chr(c)))]
t.ok(not over, 'no glyph paints below row 7: {}'.format(over[:10]))

# The 8 symbols the upstream source omits are supplied by the generator.
for ch in '$&@[\\]^|':
    t.ok(ink(ch) > 0, 'symbol {!r} is drawn, not blank'.format(ch))

# Spot-check shapes so a mis-packed font (bit order / transpose) is caught.
t.ok(ink('W') > ink('.'), "'W' has more ink than '.'")
t.eq(cols('l')[0] & 0x7f, cols('l')[0], "'l' stays inside 7 rows")
t.ok(ink('0') > 5 and ink('8') > 5, 'digits are substantial glyphs')

sys.exit(t.done())
