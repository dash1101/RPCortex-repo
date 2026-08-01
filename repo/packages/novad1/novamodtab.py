# Desc: Nova D1 module table — which hardware modules exist, and what they're called.
# File: /Packages/NovaD1/novamodtab.py
#
# Just the names. Deliberately separate from novamods, which holds the actual
# hardware PROBES: those pull in every driver they test and cost ~15 KB of RAM,
# and the home screen only ever needed the keys and labels to build its icon list.
# Importing the probes to read a list of strings meant every device paid for the
# diagnostics it might never open.
#
# novamods imports this and attaches the test functions; anything that only needs
# to know what modules exist uses this directly.
# MicroPython-safe: no f-strings.

# (key, label) — the key drives the icon and the registry pin names.
MODULES = (
    ('dht11',     'DHT11 Temp'),
    ('gps',       'GPS'),
    ('pn532',     'NFC (PN532)'),
    ('cc1101',    'Sub-GHz'),
    ('sx1276',    'LoRa'),
    ('bt',        'Bluetooth'),
    ('ir_rx',     'IR Receive'),
    ('ir_tx',     'IR Send'),
    ('ibutton',   'iButton'),
    ('sdcard',    'SD Card'),
    ('battery',   'Battery'),
    ('buzzer',    'Buzzer'),
    ('vibration', 'Vibration'),
    ('led',       'Status LED'),
)


def labels():
    """key -> label."""
    return dict(MODULES)


def keys():
    return [k for k, _l in MODULES]
