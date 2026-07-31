# novaboard: board profiles + pin resolution. This is the single source of truth for
# pins, replacing six near-identical _pin() helpers that each carried their own
# hardcoded ESP32-S3 default. Pure logic, so the whole contract tests on the host.
import sys
import _shims
_shims.install()
from _shims import T
import novaboard as nb

t = T('test_novaboard')

# ---------------------------------------------------------------- board selection
_shims.set_reg({})
t.eq(nb.board(), 'esp32s3', 'no key and an unrecognised host -> DEFAULT_BOARD')
for b in ('esp32s3', 'pico2w', 'picoplus2w'):
    t.ok(b in nb.boards(), '{} profile listed'.format(b))
t.eq(nb.boards()[0], 'esp32s3', 'shipping boards sort ahead of drafts')

_shims.set_reg({'Apps.NovaD1_Board': 'nonsense'})
t.eq(nb.board(), 'esp32s3', 'an unknown board id falls back, never leaves no pinmap')
t.eq(nb.profile()['mcu'], 'esp32s3', 'profile() follows that fallback')

_shims.set_reg({})
t.ok(nb.set_board('pico2w'), 'set_board accepts a known id')
t.eq(nb.board(), 'pico2w', 'set_board switches the active profile')
t.ok(not nb.set_board('vic20'), 'set_board rejects an unknown id')
t.eq(nb.board(), 'pico2w', 'a rejected set_board leaves the active board alone')

# A renamed board id must keep resolving, or a device configured before the rename
# is stranded with no pinmap.
_shims.set_reg({'Apps.NovaD1_Board': 'rp2350'})
t.eq(nb.board(), 'pico2w', "the legacy 'rp2350' id resolves to pico2w")
t.eq(nb.profile()['name'], 'Raspberry Pi Pico 2 W', 'and profile() follows it')
t.eq(nb.profile('rp2350')['name'], 'Raspberry Pi Pico 2 W', 'explicit alias lookup works')
t.eq(nb.check('rp2350'), [], 'check() accepts an alias too')
_shims.set_reg({})
t.ok(nb.set_board('rp2350'), 'set_board accepts the alias')
t.eq(nb.board(), 'pico2w', 'and stores the canonical id')
t.ok(nb.set_board('ESP32S3'), 'board ids are case-insensitive')
t.eq(nb.board(), 'esp32s3', 'stored lower-cased')

# ------------------------------------------------------------------- detection
# detect() must be conservative: a board it cannot identify returns None so the
# caller falls back, rather than guessing a pinmap and mis-driving hardware.
t.eq(nb.detect(), None, 'an unrecognised host (CPython on x86) detects nothing')
_shims.set_reg({})
t.ok(not nb.set_board('auto'), "'auto' fails cleanly when nothing is detected")

# The mapping itself, driven through a faked os.uname().machine.
import os as _os
_real = _os.uname


class _U:
    def __init__(s, m): s.machine = m


for mach, want in (('Raspberry Pi Pico 2 W with RP2350', 'pico2w'),
                   ('Pimoroni Pico Plus 2 W with RP2350', 'picoplus2w'),
                   ('ESP32S3 module with ESP32S3', 'esp32s3'),
                   # An RP2040 Pico W shares the header pinout but is NOT a Nova D1
                   # target -- v1.0 does not fit in 264 KB. Detecting nothing is
                   # correct; claiming it as a supported board would not be.
                   ('Raspberry Pi Pico W with RP2040', None),
                   ('Some Unknown Board', None)):
    _os.uname = (lambda m: (lambda: _U(m)))(mach)
    t.eq(nb.detect(), want, 'detect({!r})'.format(mach[:28]))

# 'Pico Plus 2' also contains 'Pico 2', so order in detect() matters.
_os.uname = lambda: _U('Pimoroni Pico Plus 2 W with RP2350')
t.eq(nb.detect(), 'picoplus2w', 'Plus is matched before the plain Pico 2 W')
t.ok(nb.set_board('auto'), "'auto' works once the board is identifiable")
t.eq(nb.board(), 'picoplus2w', "'auto' stores the detected board")

# With nothing configured, fall back to the DETECTED board rather than a hardcoded
# one -- a Pico then gets the right pinmap out of the box.
_shims.set_reg({})
t.eq(nb.board(), 'picoplus2w', 'an unconfigured device uses the detected board')
# ...but an explicit setting always wins over detection.
_shims.set_reg({'Apps.NovaD1_Board': 'esp32s3'})
t.eq(nb.board(), 'esp32s3', 'an explicit board beats detection')
_os.uname = _real
_shims.set_reg({})

# ------------------------------------------------------- resolution order matters
# The registry MUST win. A device already wired and configured by hand keeps
# working; a profile only fills in pins the user never set.
_shims.set_reg({})
t.eq(nb.pin('ir_tx'), 39, 'no override -> the board profile value')
t.eq(nb.source('ir_tx'), 'board', 'source reports it came from the profile')

_shims.set_reg({'Apps.NovaD1_PIN_ir_tx': '7'})
t.eq(nb.pin('ir_tx'), 7, 'a registry override beats the profile default')
t.eq(nb.source('ir_tx'), 'override', 'source reports the override')

_shims.set_reg({'Apps.NovaD1_PIN_ir_tx': 'not-a-pin'})
t.eq(nb.pin('ir_tx'), 39, 'a corrupt override is ignored, profile still applies')

_shims.set_reg({'Apps.NovaD1_PIN_ir_tx': ''})
t.eq(nb.pin('ir_tx'), 39, 'an empty override counts as unset')

# The legacy I2C keys predate the Apps.NovaD1_PIN_ shape and must keep working.
_shims.set_reg({'Apps.NovaD1_SDA': '21', 'Apps.NovaD1_SCL': '22'})
t.eq(nb.pin('sda'), 21, 'legacy Apps.NovaD1_SDA still overrides sda')
t.eq(nb.pin('scl'), 22, 'legacy Apps.NovaD1_SCL still overrides scl')
_shims.set_reg({})
t.eq(nb.pin('sda'), 8, 'sda falls back to the profile when unset')

# --------------------------------------------------- opt-in pins stay unset
# novapower reads the battery/VBUS pins ONLY when configured, so an unwired
# floating ADC cannot produce a lying battery icon. No profile may default them.
_shims.set_reg({})
for name in nb.OPT_IN:
    t.eq(nb.pin(name), None, '{} is None until configured'.format(name))
    t.eq(nb.source(name), 'unset', '{} reports unset'.format(name))
for bid in nb.boards():
    p = nb.profile(bid).get('pins', {})
    for name in nb.OPT_IN:
        t.ok(name not in p, '{} does not default {} (keeps the guard)'.format(bid, name))

# A caller may still pass its own fallback — that is how novamods' manual test path
# keeps working while novapower's status-bar read stays guarded.
t.eq(nb.pin('battery', 1), 1, "a caller's own default still applies")
_shims.set_reg({'Apps.NovaD1_PIN_battery': '4'})
t.eq(nb.pin('battery'), 4, 'once configured, the opt-in pin resolves')

# ----------------------------------------------------------------- set / clear
_shims.set_reg({})
t.ok(nb.set_pin('ir_tx', 12), 'set_pin stores an override')
t.eq(nb.pin('ir_tx'), 12, 'the stored override is what resolves')
t.ok(nb.clear_pin('ir_tx'), 'clear_pin succeeds')
t.eq(nb.pin('ir_tx'), 39, 'clearing reverts to the board default, not to nothing')
t.ok(not nb.set_pin('ir_tx', 'abc'), 'set_pin rejects a non-numeric value')
t.ok(not nb.set_pin('ir_tx', -3), 'set_pin rejects a negative pin')
t.eq(nb.pin('ir_tx'), 39, 'a rejected set_pin does not corrupt the value')
nb.set_pin('ir_tx', 5)
t.ok(nb.set_pin('ir_tx', ''), 'an empty value clears rather than storing garbage')
t.eq(nb.pin('ir_tx'), 39, 'and the default is back')

# names()/pins() are what a pins editor lists.
_shims.set_reg({})
ns = nb.names('esp32s3')
t.ok('ir_tx' in ns and 'spi_sck' in ns, 'names() covers the wiring pins')
for name in nb.OPT_IN:
    t.ok(name in ns, 'names() offers the opt-in pin {} too'.format(name))
t.eq(ns, sorted(ns), 'names() is sorted for a stable display order')
t.eq(set(nb.pins('esp32s3').keys()), set(ns), 'pins() covers exactly names()')

# ------------------------------------------------------------------- validation
# Both shipped profiles must be internally consistent.
for bid in nb.boards():
    t.eq(nb.check(bid), [], '{} profile validates clean'.format(bid))

# The ESP32-S3 map must still be byte-identical to what the drivers hardcoded,
# or this refactor silently re-pins working hardware.
WAS = {'sda': 8, 'scl': 9, 'enc_a': 4, 'enc_b': 5, 'enc_sw': 6, 'btn1': 7, 'btn2': 16,
       'spi_sck': 12, 'spi_mosi': 11, 'spi_miso': 13, 'sd_cs': 15, 'cc_cs': 10,
       'cc_gdo0': 14, 'sx_cs': 21, 'sx_rst': 47, 'ir_tx': 39, 'ir_rx': 38,
       'gps_tx': 17, 'gps_rx': 18, 'buzzer': 40, 'vibe': 41, 'led': 48, 'dht': 2,
       'ibutton': 1}
got = nb.profile('esp32s3')['pins']
for name in sorted(WAS.keys()):
    t.eq(got.get(name), WAS[name], 'esp32s3 {} unchanged from the old hardcoded value'.format(name))

# check() has to actually catch things, or it is decoration. Inject bad profiles.
nb._PROFILES['_dup'] = {'name': 'dup', 'mcu': 'esp32s3',
                        'pins': {'ir_tx': 5, 'ir_rx': 5}}
t.ok(any('used by both' in m for m in nb.check('_dup')), 'catches two roles on one pin')

# RP2 ties SPI/I2C to fixed GPIO groups: a map can be unassignable even though the
# pin numbers exist. GPIO 19 is SPI0 TX, so it cannot be SCK.
nb._PROFILES['_badspi'] = {'name': 'bad', 'mcu': 'rp2350',
                           'pins': {'spi_sck': 19, 'spi_mosi': 18, 'spi_miso': 16}}
probs = nb.check('_badspi')
t.ok(any('cannot be sck' in m for m in probs), 'catches an illegal RP2 SPI role')

# SPI0 pins mixed with SPI1 pins cannot form one bus.
nb._PROFILES['_split'] = {'name': 'split', 'mcu': 'rp2350',
                          'pins': {'spi_sck': 18, 'spi_mosi': 19, 'spi_miso': 8}}
t.ok(any('span SPI controllers' in m for m in nb.check('_split')),
     'catches pins spanning two SPI controllers')

# I2C0 SDA with I2C1 SCL is a real and easy mistake.
nb._PROFILES['_badi2c'] = {'name': 'bi2c', 'mcu': 'rp2350', 'pins': {'sda': 4, 'scl': 7}}
t.ok(any('I2C' in m for m in nb.check('_badi2c')), 'catches a mismatched I2C pair')

# GPIO 23/24/25/29 belong to the wireless module on Pico W-class boards; they look
# free on a pinout diagram, which is exactly why this check exists.
nb._PROFILES['_res'] = {'name': 'res', 'mcu': 'rp2350', 'reserved': (23, 24, 25, 29),
                        'pins': {'led': 25}}
t.ok(any('reserved' in m for m in nb.check('_res')), 'catches a board-reserved GPIO')
for b in ('pico2w', 'picoplus2w'):
    for g in (23, 24, 25, 29):
        t.ok(g in nb.profile(b)['reserved'],
             '{} reserves GPIO {} for the wireless module'.format(b, g))
    t.ok(not (set(nb.profile(b)['pins'].values()) & set(nb.profile(b)['reserved'])),
         '{} assigns no reserved GPIO'.format(b))

# An ESP32 profile must NOT be held to the RP2 pin groups (it has a GPIO matrix).
nb._PROFILES['_esp'] = {'name': 'esp', 'mcu': 'esp32s3',
                        'pins': {'spi_sck': 19, 'spi_mosi': 18, 'spi_miso': 16}}
t.eq(nb.check('_esp'), [], 'ESP32 pins are not checked against RP2 groups')

for k in ('_dup', '_badspi', '_split', '_badi2c', '_res', '_esp'):
    del nb._PROFILES[k]

# --------------------------------------------------- the Pimoroni is a drop-in
# It shares the standard Pico header, so it inherits the map rather than carrying a
# copy. Asserting that is what stops the two silently drifting apart.
t.eq(nb.profile('picoplus2w')['pins'], nb.profile('pico2w')['pins'],
     'picoplus2w inherits the pico2w pinmap exactly (drop-in upgrade)')
t.ok(nb.profile('picoplus2w')['pins'] is not nb.profile('pico2w')['pins'],
     'but holds its own dict, so editing one cannot mutate the other')
t.eq(nb.profile('picoplus2w')['mcu'], 'rp2350b', 'picoplus2w is the B-series part')

# The pin budget is the whole reason check() exists -- keep the numbers honest.
# SD shares SPI0 (freeing the 3 dedicated-bus pins), so the map fits within the 26
# usable GPIO with the kill switch AND headroom to spare.
used, res = nb.usable_pins('pico2w')
t.ok(used <= 26, 'the pico2w map fits within 26 usable GPIO (uses {})'.format(used))
t.eq(res, 4, 'and 4 more are reserved by the board')
t.eq(nb.profile('pico2w')['pins'].get('killsw'), 8, 'the kill switch is on GPIO 8')
t.ok('sd_sck' not in nb.profile('pico2w')['pins'],
     'SD shares SPI0 on pico2w (no dedicated SD bus pins)')
t.ok('ibutton' not in nb.profile('pico2w')['pins'],
     'ibutton stays unassigned on pico2w -- needs a GPIO expander')
t.ok('ibutton' in nb.profile('esp32s3')['pins'], 'esp32s3 has room for it')
for b in nb.boards():
    if nb.profile(b)['mcu'].startswith('rp2'):
        t.eq(nb.profile(b).get('display_bus'), 'i2c',
             '{} records I2C as the decided display interface'.format(b))

# ------------------------------------------------- drivers share the one resolver
# Mirrors the novacore delegation check: prove every driver actually resolves to
# this module at import time rather than keeping its own copy.
for mod in ('novamods', 'novair', 'novalora', 'novacc', 'novasound', 'novapower'):
    m = __import__(mod)
    fn = getattr(m, '_pin', None)
    t.ok(fn is not None, '{} exposes _pin'.format(mod))
    t.ok(getattr(m, '_board', None) is nb, '{} imports novaboard'.format(mod))

sys.exit(t.done())
