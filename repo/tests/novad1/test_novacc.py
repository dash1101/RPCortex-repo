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
t.ok(C.encode_decoded('Holtek', '00', 40, 430) is None, 'unknown protocol -> None')
t.ok(C.encode_decoded('CAME', '0A', 12, 0) is None, 'no TE -> None')

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
