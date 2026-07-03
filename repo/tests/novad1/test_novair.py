# IR encoders (novair.encode): pulse-distance (NEC/Sony) structure + a full,
# independent round-trip decode of the new RC5/RC5X bi-phase encoder. RC6 Mode 0 is
# checked structurally (leader + valid unit timings). Zero hardware.
import sys
import _shims
_shims.install()
from _shims import T
import novair

t = T('test_novair')


def rc5_decode(times, half=889):
    """Independent RC5 decoder: expand merged mark/space timings back to half-bits and
    read the 14 bi-phase bits. Proves encode() emits the right levels + bit order."""
    halfs = [0]                       # bit-1 opens with a dropped leading (idle) space
    lvl = 1                           # the emitted list starts on a mark
    for d in times:
        halfs += [lvl] * int(round(d / float(half)))
        lvl ^= 1
    if len(halfs) % 2:
        halfs.append(0)               # a dropped trailing space
    bits = []
    for i in range(0, len(halfs) - 1, 2):
        bits.append(1 if (halfs[i], halfs[i + 1]) == (0, 1) else 0)
    return bits


# --- NEC (pulse-distance) structure ---
r = novair.encode('NEC', '04', '08')
t.ok(r is not None, 'NEC encodes')
freq, tm = r
t.eq(freq, 38000, 'NEC carrier 38 kHz')
t.eq((tm[0], tm[1]), (9000, 4500), 'NEC 9000/4500 header')
t.eq(len(tm), 2 + 32 * 2 + 1, 'NEC = header + 32 bits + stop')

# --- Sony SIRC structure ---
r = novair.encode('SIRC', '01', '12')
freq, tm = r
t.eq(freq, 40000, 'Sony carrier 40 kHz')
t.eq((tm[0], tm[1]), (2400, 600), 'Sony 2400/600 header')

# --- RC5 / RC5X: full round-trip ---
for addr, cmd in ((0, 0), (1, 2), (20, 53), (31, 63)):
    freq, tm = novair.encode('RC5', '{:02X}'.format(addr), '{:02X}'.format(cmd))
    t.eq(freq, 36000, 'RC5 carrier 36 kHz ({},{})'.format(addr, cmd))
    t.ok(all(d in (889, 1778) for d in tm), 'RC5 timings are 1 or 2 half-bits')
    bits = rc5_decode(tm)
    t.eq(len(bits), 14, 'RC5 decodes to 14 bits ({},{})'.format(addr, cmd))
    t.eq(bits[0], 1, 'RC5 start bit is 1')
    t.eq(bits[2], 0, 'RC5 toggle fired as 0')
    da = sum(bits[3 + i] << (4 - i) for i in range(5))
    dc = sum(bits[8 + i] << (5 - i) for i in range(6))
    t.eq(da, addr, 'RC5 address round-trips')
    t.eq(dc, cmd, 'RC5 command round-trips')

# RC5X: 7-bit command uses the 2nd start bit as the inverted MSB
freq, tm = novair.encode('RC5X', '05', '7F')      # cmd 127 -> bit6 set -> start2 = 0
bits = rc5_decode(tm)
t.eq(bits[1], 0, 'RC5X field bit = inverted command MSB (set -> 0)')
da = sum(bits[3 + i] << (4 - i) for i in range(5))
dc6 = sum(bits[8 + i] << (5 - i) for i in range(6))
t.eq(da, 5, 'RC5X address round-trips')
t.eq(dc6, 0x3F, 'RC5X low 6 command bits round-trip')

# --- RC6 Mode 0: structural (leader + valid RC6 unit timings) ---
freq, tm = novair.encode('RC6', 'A0', '1C')
t.eq(freq, 36000, 'RC6 carrier 36 kHz')
t.eq((tm[0], tm[1]), (2666, 889), 'RC6 leader 2666/889')
t.ok(all(d in (444, 888, 1332) for d in tm[2:]), 'RC6 body uses 444/888/1332 units')
t.ok(len(tm) > 24, 'RC6 emits a full 21-bit frame')

# --- unsupported protocol returns None ---
t.eq(novair.encode('BOGUS', '00', '00'), None, 'unknown protocol -> None')

sys.exit(t.done())
