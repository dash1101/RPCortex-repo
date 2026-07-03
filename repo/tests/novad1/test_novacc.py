# Sub-GHz: Flipper .sub parse (RAW + decoded Key), to_flipper, fire routing,
# and the decoded-protocol encoders (Princeton / CAME / NICE FLO) vs firmware.
import sys
import _shims
_shims.install()
from _shims import T
import novacc as C

t = T('test_novacc')

# --- RAW .sub parse (abs durations across multiple RAW_Data lines) ---
RAW = ("Filetype: Flipper SubGhz RAW File\nVersion: 1\nFrequency: 433920000\n"
       "Preset: FuriHalSubGhzPresetOok650Async\nProtocol: RAW\n"
       "RAW_Data: 347 -347 347 -1041\nRAW_Data: 1041 -347\n")
d = C.parse_flipper(RAW)
t.eq(d['raw'], [347, 347, 347, 1041, 1041, 347], 'RAW parse (abs, multi-line)')
t.ok(abs(d['freq_mhz'] - 433.92) < 0.01, 'RAW frequency MHz')

# --- to_flipper round-trip (our timings -> RAW .sub -> back) ---
sub = C.to_flipper('x', [347, 347, 347, 1041], freq_mhz=915.0)
t.eq(C.parse_flipper(sub)['raw'], [347, 347, 347, 1041], 'to_flipper round-trip')
line = [l for l in sub.split('\n') if l.startswith('RAW_Data')][0]
vals = [int(v) for v in line.split(':', 1)[1].split()]
t.ok(vals[0] > 0 and vals[1] < 0 and vals[2] > 0, 'RAW signs alternate +,-,+')

# --- decoded Key file parse ---
KEY = ("Filetype: Flipper SubGhz Key File\nVersion: 1\nFrequency: 433920000\n"
       "Protocol: Princeton\nBit: 24\nKey: 00 00 00 00 00 95 D5 D4\nTE: 400\n")
k = C.parse_flipper(KEY)
t.ok(k['protocol'] == 'Princeton' and k['bit'] == 24 and k['te'] == 400, 'Key file fields')
t.ok('raw' not in k, 'Key file has no raw')

# --- Princeton encoder (exact per firmware) ---
t.eq(C._encode_princeton(0b1010, 4, 400),
     [1200, 400, 400, 1200, 1200, 400, 400, 1200, 400, 12000], 'Princeton bit + guard')
enc = C.encode_decoded('Princeton', '95 D5 D4', 24, 400)
t.eq(len(enc), 50, 'Princeton 24-bit length (24*2+2)')

# --- CAME / NICE FLO ---
came = C.encode_decoded('CAME', '00 0A', 12, 320)
t.ok(len(came) == 26 and came[0] == 320 and came[-1] == 320 * 47, 'CAME 12-bit shape+header')
nice = C.encode_decoded('Nice FLO', '00 0F', 12, 700)
t.ok(len(nice) == 26 and nice[0] == 700 and nice[-1] == 700 * 36, 'NICE FLO shape+header')
t.ok(C.encode_decoded('__nope__', '00', 12, 400) is None, 'unknown protocol -> None')
t.ok(C.encode_decoded('CAME', '0A', 12, 0) is None, 'no TE -> None')


# --- new firmware-grounded protocols: round-trip decode proves bit encoding + MSB order ---
def _dec_camelike(times, te, n, bit1_long_low=True):
    # [start_high, (low,high) x n, trailing header]; recover the value MSB-first.
    v = 0
    for k in range(n):
        low, high = times[1 + 2 * k], times[2 + 2 * k]
        long_low = low > high
        one = long_low if bit1_long_low else (not long_low)
        v = (v << 1) | (1 if one else 0)
    return v


def _dec_linear(times, te, n):
    v = 0
    for k in range(n):
        high, low = times[2 * k], times[2 * k + 1]
        one = (high > te * 2) if k == n - 1 else (high > low)   # last low is the guard
        v = (v << 1) | (1 if one else 0)
    return v

for val, bits in ((0xABC, 12), (0x000, 12), (0xFFF, 12), (0x5A5, 12)):
    hx = '{:02X} {:02X}'.format((val >> 8) & 0xFF, val & 0xFF)
    hol = C.encode_decoded('Holtek', hx, bits, 430)
    t.eq(_dec_camelike(hol, 430, bits, True), val, 'Holtek round-trips 0x{:03X}'.format(val))
    t.ok(hol[-1] == 430 * 36, 'Holtek 36*te preamble')
    ans = C.encode_decoded('Ansonic', hx, bits, 555)
    t.eq(_dec_camelike(ans, 555, bits, False), val, 'Ansonic round-trips 0x{:03X}'.format(val))
    t.ok(ans[-1] == 555 * 35, 'Ansonic 35*te preamble')

for val, bits in ((0x2AB, 10), (0x000, 10), (0x3FF, 10), (0x155, 10)):
    hx = '{:02X} {:02X}'.format((val >> 8) & 0xFF, val & 0xFF)
    lin = C.encode_decoded('Linear', hx, bits, 500)
    t.eq(_dec_linear(lin, 500, bits), val, 'Linear round-trips 0x{:03X}'.format(val))
    t.ok(lin[-1] in (500 * 42, 500 * 44), 'Linear inter-frame guard')

# --- fire_text routing (monkeypatch the hardware TX) ---
calls = []
C.fire_timing = lambda times, freq=None: (calls.append((list(times), freq)) or True)
t.ok(C.fire_text(RAW) and calls[-1][0] == d['raw'], 'fire RAW .sub')
t.ok(C.fire_text(KEY) and len(calls[-1][0]) == 50, 'fire decoded Princeton Key .sub')
t.ok(C.fire_text('347,347,1041\n347') and calls[-1][0] == [347, 347, 1041, 347], 'fire plain list')
calls.clear()
C.fire_text('100,200', repeats=4)
t.eq(len(calls), 4, 'repeats fire N bursts')
calls.clear()
n = [0]
C.fire_text('100,200', repeats=10, cancel=lambda: (n.__setitem__(0, n[0] + 1) or n[0] > 2))
t.ok(len(calls) <= 3, 'cancel aborts between bursts')

sys.exit(t.done())
