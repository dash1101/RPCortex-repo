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
t.eq(nb.board(), 'esp32s3', 'no key -> the shipping board is the default')
t.ok('esp32s3' in nb.boards() and 'rp2350' in nb.boards(), 'both profiles listed')
t.eq(nb.boards()[0], 'esp32s3', 'shipping boards sort ahead of drafts')

_shims.set_reg({'Apps.NovaD1_Board': 'nonsense'})
t.eq(nb.board(), 'esp32s3', 'an unknown board id falls back, never leaves no pinmap')
t.eq(nb.profile()['mcu'], 'esp32s3', 'profile() follows that fallback')

_shims.set_reg({})
t.ok(nb.set_board('rp2350'), 'set_board accepts a known id')
t.eq(nb.board(), 'rp2350', 'set_board switches the active profile')
t.ok(not nb.set_board('vic20'), 'set_board rejects an unknown id')
t.eq(nb.board(), 'rp2350', 'a rejected set_board leaves the active board alone')

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
t.ok(25 in nb.profile('rp2350')['reserved'],
     'the rp2350 draft records the wireless-module pins as reserved')

# An ESP32 profile must NOT be held to the RP2 pin groups (it has a GPIO matrix).
nb._PROFILES['_esp'] = {'name': 'esp', 'mcu': 'esp32s3',
                        'pins': {'spi_sck': 19, 'spi_mosi': 18, 'spi_miso': 16}}
t.eq(nb.check('_esp'), [], 'ESP32 pins are not checked against RP2 groups')

for k in ('_dup', '_badspi', '_split', '_badi2c', '_res', '_esp'):
    del nb._PROFILES[k]

# ------------------------------------------------- drivers share the one resolver
# Mirrors the novacore delegation check: prove every driver actually resolves to
# this module at import time rather than keeping its own copy.
for mod in ('novamods', 'novair', 'novalora', 'novacc', 'novasound', 'novapower'):
    m = __import__(mod)
    fn = getattr(m, '_pin', None)
    t.ok(fn is not None, '{} exposes _pin'.format(mod))
    t.ok(getattr(m, '_board', None) is nb, '{} imports novaboard'.format(mod))

sys.exit(t.done())
