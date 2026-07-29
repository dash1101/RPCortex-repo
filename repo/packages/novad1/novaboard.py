# Desc: Nova D1 board profiles — one source of truth for pins and buses.
# File: /Packages/NovaD1/novaboard.py
#
# Before this module, every driver carried its own `_pin()` helper with its own
# hardcoded ESP32-S3 default: novamods, novair, novalora, novacc, novasound and
# novapower each had a copy. Changing a wire meant `reg set Apps.NovaD1_PIN_<x>`
# for every pin, with no list of what the names were and no way to see what was
# actually in effect. Moving to another MCU meant editing six files.
#
# So: a board PROFILE holds the wiring defaults, and every driver asks this module.
# Adding a board is a data change; the drivers never change.
#
# Resolution order, highest wins:
#   1. a registry override   (Apps.NovaD1_PIN_<name>, set by the user)
#   2. the active profile    (Apps.NovaD1_Board, default 'esp32s3')
#   3. the caller's fallback (pin(name, default) — None if not given)
#
# The registry deliberately WINS. Any board already configured by hand keeps
# working exactly as before; a profile only supplies defaults for pins the user
# never set. `source(name)` reports which of the three a value came from, which is
# what makes a pins editor honest about what it is showing.
#
# This module is a LEAF: it imports only novacore, so any driver can depend on it
# without an import cycle. See ARCHITECTURE.md for the layer map.
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

from novacore import reg as _reg, save_reg as _save_reg

VERSION = '1.0'

_KEY_BOARD = 'Apps.NovaD1_Board'
_KEY_PREFIX = 'Apps.NovaD1_PIN_'
DEFAULT_BOARD = 'esp32s3'

# Pins that must stay UNSET unless the user configures them. novapower reads the
# battery/VBUS pins only when they are configured, so an unwired floating ADC can
# never produce a lying battery icon. Giving these a profile default would silently
# turn that guard off, so no profile may list them.
OPT_IN = ('battery', 'vbus')

# Legacy key names kept working: the I2C pins shipped as Apps.NovaD1_SDA/_SCL
# rather than the Apps.NovaD1_PIN_ shape everything else uses.
_ALIASES = {'sda': 'Apps.NovaD1_SDA', 'scl': 'Apps.NovaD1_SCL'}


_PROFILES = {
    # ---------------------------------------------------------------- ESP32-S3
    # The shipping Nova D1. These are the values the drivers used to hardcode, so
    # a device with no overrides behaves exactly as it did before this module.
    'esp32s3': {
        'name': 'ESP32-S3 (Nova D1 rev A)',
        'mcu': 'esp32s3',
        'status': 'shipping',
        'pins': {
            'sda': 8, 'scl': 9,                        # I2C: OLED, RTC, PN532
            'enc_a': 4, 'enc_b': 5, 'enc_sw': 6,       # EC11 rotary encoder
            'btn1': 7, 'btn2': 16,                     # btn2=16 keeps 15 free for SD CS
            'spi_sck': 12, 'spi_mosi': 11, 'spi_miso': 13,
            'sd_cs': 15,
            'cc_cs': 10, 'cc_gdo0': 14,                # CC1101 sub-GHz
            'sx_cs': 21, 'sx_rst': 47,                 # SX1276 LoRa
            'ir_tx': 39, 'ir_rx': 38,
            'gps_tx': 17, 'gps_rx': 18,
            'buzzer': 40, 'vibe': 41,
            'led': 48,                                 # onboard RGB on most devkits
            'dht': 2,
            'ibutton': 1,
        },
        'notes': 'One shared SPI bus for SD + both radios.',
    },
    # ----------------------------------------------------------------- RP2350
    # DRAFT — placeholders, not a decided pinmap. The pin budget is the open task
    # for the port (roughly low-30s pins needed vs ~31 exposed), and the display
    # interface is undecided. What matters here is that these respect the RP2
    # fixed peripheral pin groups, which check() verifies. Finalise before use.
    'rp2350': {
        'name': 'RP2350 / Pico Plus 2 W (DRAFT)',
        'mcu': 'rp2350',
        'status': 'draft',
        # GPIO 23/24/25/29 are wired to the wireless module on Pico W-class boards
        # (WL_ON, WL_DATA, WL_CS, WL_CLK + VSYS sense) and are NOT free. That
        # leaves GPIO 0-22 and 26-28 — 26 usable pins on the standard header.
        'reserved': (23, 24, 25, 29),
        'pins': {
            'sda': 4, 'scl': 5,                        # I2C0, the Qw/ST bus
            'enc_a': 14, 'enc_b': 15, 'enc_sw': 13,    # EC11 rotary encoder
            'btn1': 22, 'btn2': 26,
            'spi_sck': 18, 'spi_mosi': 19, 'spi_miso': 16,   # SPI0: both radios
            'sd_cs': 9,                                # SD on its own bus, SPI1
            'sd_sck': 10, 'sd_mosi': 11, 'sd_miso': 8,
            'cc_cs': 17, 'cc_gdo0': 20,                # CC1101 sub-GHz
            'sx_cs': 21, 'sx_rst': 12,                 # SX1276 LoRa
            'ir_tx': 6, 'ir_rx': 7,
            'gps_tx': 0, 'gps_rx': 1,
            'buzzer': 27, 'vibe': 28,
            'led': 2,                                  # external RGB; the onboard
                                                       # LED sits on the radio chip
            'dht': 3,
        },
        # 'ibutton' is deliberately absent: this map already consumes all 26 usable
        # header pins, which is the pin-budget squeeze the port has to solve. The
        # fix is an I2C expander (PCF8574) or a 74HC165 for the buttons and DIP
        # switches, collapsing ~7 pins into ~2 and freeing room for the rest.
        'notes': 'DRAFT, at the 26-pin ceiling. SD split onto SPI1 so LoRa RX and '
                 'card writes do not contend. Buttons want a GPIO expander.',
    },
}

# RP2 peripheral pins are fixed to GPIO groups — there is no ESP32-style GPIO
# matrix, so a pinmap has to be built around the valid groups. The pattern
# repeats every 8 GPIO: role is gpio % 4 (0=RX/MISO, 1=CSn, 2=SCK, 3=TX/MOSI),
# and which controller it belongs to is (gpio // 8) % 2. I2C alternates on
# gpio % 4 as well: 0/1 = I2C0 SDA/SCL, 2/3 = I2C1 SDA/SCL.
_RP2_SPI_ROLE = {0: 'miso', 1: 'cs', 2: 'sck', 3: 'mosi'}


def _rp2_spi(gpio):
    """Return (controller, role) for an RP2 GPIO used as SPI, e.g. (0, 'sck')."""
    return (gpio // 8) % 2, _RP2_SPI_ROLE[gpio % 4]


def _rp2_i2c(gpio):
    """Return (controller, role) for an RP2 GPIO used as I2C, e.g. (0, 'sda')."""
    m = gpio % 4
    if m == 0:
        return 0, 'sda'
    if m == 1:
        return 0, 'scl'
    if m == 2:
        return 1, 'sda'
    return 1, 'scl'


# ---------------------------------------------------------------- board choice
def boards():
    """Available profile ids, shipping ones first."""
    ids = list(_PROFILES.keys())
    ids.sort(key=lambda i: (_PROFILES[i].get('status') != 'shipping', i))
    return ids


def board():
    """The active board id. Falls back to the default if the key names an
    unknown profile, so a typo can never leave the device with no pinmap."""
    b = _reg(_KEY_BOARD, DEFAULT_BOARD)
    return b if b in _PROFILES else DEFAULT_BOARD


def set_board(board_id):
    """Switch the active profile. Returns False for an unknown id."""
    if board_id not in _PROFILES:
        return False
    return _save_reg(_KEY_BOARD, board_id)


def profile(board_id=None):
    """The profile dict for `board_id` (default: the active board)."""
    return _PROFILES.get(board_id or board(), _PROFILES[DEFAULT_BOARD])


def names(board_id=None):
    """Every pin name this board defines, sorted, plus the opt-in pins so a
    pins editor can offer them even though they have no default."""
    ns = list(profile(board_id).get('pins', {}).keys())
    for n in OPT_IN:
        if n not in ns:
            ns.append(n)
    ns.sort()
    return ns


# ------------------------------------------------------------------ resolution
def _short(name):
    """Accept either a short pin name ('spi_sck') or a full registry key
    ('Apps.NovaD1_PIN_spi_sck'). The drivers grew both conventions — novalora
    passed full keys, everything else short names — so both resolve here and no
    call site had to change when they moved onto this module."""
    if name.startswith(_KEY_PREFIX):
        return name[len(_KEY_PREFIX):]
    for shortname, legacy in _ALIASES.items():
        if name == legacy:
            return shortname
    return name


def _key(name):
    return _ALIASES.get(name, _KEY_PREFIX + name)


def _override(name):
    """The user's registry value for `name` as an int, or None if unset/invalid."""
    v = _reg(_key(name), '')
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def pin(name, default=None):
    """Resolve a pin: registry override, else the active profile, else `default`.

    Callers that need a pin to be explicitly configured pass no default and check
    for None — that is how novapower keeps an unwired battery ADC from reading."""
    name = _short(name)
    v = _override(name)
    if v is not None:
        return v
    p = profile().get('pins', {})
    if name in p:
        return p[name]
    return default


def source(name):
    """Where pin(name) got its value: 'override', 'board', or 'unset'."""
    name = _short(name)
    if _override(name) is not None:
        return 'override'
    if name in profile().get('pins', {}):
        return 'board'
    return 'unset'


def pins(board_id=None):
    """The full resolved map {name: pin-or-None} for the active board."""
    out = {}
    for n in names(board_id):
        out[n] = pin(n)
    return out


def set_pin(name, value):
    """Override a pin. `value` None or '' clears the override, reverting to the
    board default. Returns False if the value is not a usable pin number."""
    name = _short(name)
    if value is None or value == '':
        return clear_pin(name)
    try:
        v = int(value)
    except (TypeError, ValueError):
        return False
    if v < 0:
        return False
    return _save_reg(_key(name), str(v))


def clear_pin(name):
    """Drop the override so the board default applies again."""
    return _save_reg(_key(_short(name)), '')


# ------------------------------------------------------------------ validation
def check(board_id=None):
    """Sanity-check a profile: duplicate pins, and on RP2 whether the SPI/I2C
    assignments land on legal GPIO for those peripherals. Returns a list of
    problem strings, empty when the map is clean.

    RP2 ties SPI/I2C to fixed GPIO groups, so a pinmap that looks reasonable can
    simply be unassignable. This catches that on the host, before wiring."""
    prof = profile(board_id)
    p = prof.get('pins', {})
    problems = []

    # A GPIO driven by two things at once is a wiring bug on any MCU.
    seen = {}
    for name in sorted(p.keys()):
        g = p[name]
        if g in seen:
            problems.append('pin {} used by both {} and {}'.format(g, seen[g], name))
        else:
            seen[g] = name

    # Pins the board itself owns — on Pico W-class boards the wireless module takes
    # four GPIO that look free in a pinout diagram but are not.
    res = prof.get('reserved', ())
    for name in sorted(p.keys()):
        if p[name] in res:
            problems.append('{}: GPIO {} is reserved by the board'
                            .format(name, p[name]))

    if prof.get('mcu', '').startswith('rp2'):
        for bus, sck, mosi, miso in (('SPI0', 'spi_sck', 'spi_mosi', 'spi_miso'),
                                     ('SD SPI', 'sd_sck', 'sd_mosi', 'sd_miso')):
            trio = [(r, p[n]) for r, n in (('sck', sck), ('mosi', mosi), ('miso', miso))
                    if n in p]
            if len(trio) != 3:
                continue
            ctrls = set()
            for role, g in trio:
                c, actual = _rp2_spi(g)
                ctrls.add(c)
                if actual != role:
                    problems.append('{}: GPIO {} cannot be {} (it is SPI {})'
                                    .format(bus, g, role, actual))
            if len(ctrls) > 1:
                problems.append('{}: pins span SPI controllers {}'
                                .format(bus, sorted(ctrls)))
        if 'sda' in p and 'scl' in p:
            cs, rs = _rp2_i2c(p['sda'])
            cc, rc = _rp2_i2c(p['scl'])
            if rs != 'sda':
                problems.append('I2C: GPIO {} cannot be SDA (it is {})'
                                .format(p['sda'], rs))
            if rc != 'scl':
                problems.append('I2C: GPIO {} cannot be SCL (it is {})'
                                .format(p['scl'], rc))
            if rs == 'sda' and rc == 'scl' and cs != cc:
                problems.append('I2C: SDA is on I2C{} but SCL is on I2C{}'
                                .format(cs, cc))
    return problems
