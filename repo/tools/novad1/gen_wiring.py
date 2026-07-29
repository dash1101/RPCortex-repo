# Regenerates the per-board pin tables in the Nova D1 wiring guide, straight from
# novaboard's board profiles.
#
# The wiring doc and the code had drifted before (the doc put the status LED on GPIO
# 42 while the code used 48, and documented registry keys that never existed). The
# tables are generated so that cannot happen again: novaboard is the single source of
# truth, and this only rewrites the block between the GENERATED markers. Everything
# outside them is hand-written prose and is left alone.
#
#   python3 gen_wiring.py            # rewrite the doc in place
#   python3 gen_wiring.py --check    # exit 1 if the doc is out of date (no write)
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', '..', 'packages', 'novad1'))

DOC = os.path.normpath(os.path.join(_HERE, '..', '..', '..', '..',
                                    'NovaLabs', 'docs', 'novad1-wiring.md'))
BEGIN = '<!-- BEGIN GENERATED PINMAPS -->'
END = '<!-- END GENERATED PINMAPS -->'

# Logical groups, in the order a person actually wires things up.
GROUPS = (
    ('I2C bus', ('sda', 'scl'), 'Display, PN532, RTC all share this'),
    ('SPI bus (radios)', ('spi_sck', 'spi_mosi', 'spi_miso'), 'Separate CS per device'),
    ('microSD', ('sd_cs', 'sd_sck', 'sd_mosi', 'sd_miso'), ''),
    ('CC1101 sub-GHz', ('cc_cs', 'cc_gdo0'), ''),
    ('SX1276 LoRa', ('sx_cs', 'sx_rst'), 'DIO0 not needed - the driver polls'),
    ('GPS', ('gps_tx', 'gps_rx'), 'UART, 9600 baud'),
    ('Controls', ('enc_a', 'enc_b', 'enc_sw', 'btn1', 'btn2'), 'EC11 encoder + 2 buttons'),
    ('Infrared', ('ir_tx', 'ir_rx'), 'TX is PWM at 38 kHz'),
    ('Feedback', ('buzzer', 'vibe', 'led'), ''),
    ('Sensors', ('dht', 'ibutton'), ''),
    ('Power sense', ('battery', 'vbus'), 'Optional - unset unless wired'),
)

WHAT = {
    'sda': 'I2C data', 'scl': 'I2C clock',
    'spi_sck': 'SPI clock', 'spi_mosi': 'SPI out (MOSI)', 'spi_miso': 'SPI in (MISO)',
    'sd_cs': 'SD chip select', 'sd_sck': 'SD clock', 'sd_mosi': 'SD out',
    'sd_miso': 'SD in',
    'cc_cs': 'CC1101 chip select', 'cc_gdo0': 'CC1101 GDO0 (data)',
    'sx_cs': 'SX1276 chip select (NSS)', 'sx_rst': 'SX1276 reset',
    'gps_tx': 'MCU TX -> GPS RX', 'gps_rx': 'MCU RX <- GPS TX',
    'enc_a': 'Encoder A', 'enc_b': 'Encoder B', 'enc_sw': 'Encoder button (Select)',
    'btn1': 'Button 1 (Back)', 'btn2': 'Button 2 (Home)',
    'ir_tx': 'IR emitter', 'ir_rx': 'IR receiver',
    'buzzer': 'Buzzer', 'vibe': 'Vibration motor', 'led': 'Status LED',
    'dht': 'DHT11/22 data', 'ibutton': 'iButton / 1-Wire',
    'battery': 'Battery ADC (via divider)', 'vbus': 'USB-power sense',
}


def _table(board_id, nb):
    prof = nb.profile(board_id)
    pins = prof.get('pins', {})
    used, nres = nb.usable_pins(board_id)
    out = []
    out.append('### {}  <code>{}</code>'.format(prof.get('name', board_id), board_id))
    out.append('')
    bits = ['**{}**'.format(prof.get('mcu', '?'))]
    if prof.get('status') != 'shipping':
        bits.append('status: **{}**'.format(prof.get('status', '?')))
    bits.append('{} GPIO assigned'.format(used))
    if prof.get('display_bus'):
        bits.append('display on **{}**'.format(prof['display_bus'].upper()))
    out.append(' · '.join(bits))
    out.append('')
    if prof.get('reserved'):
        out.append('> **Do not use GPIO {}** — the board itself owns them '
                   '(wireless module / VSYS sense). They look free on a pinout '
                   'diagram but are not.'
                   .format(', '.join(str(g) for g in prof['reserved'])))
        out.append('')
    out.append('| Group | Signal | GPIO | Notes |')
    out.append('|---|---|---|---|')
    for label, names, note in GROUPS:
        present = [n for n in names if n in pins]
        optional = [n for n in names if n not in pins and n in nb.OPT_IN]
        rows = present + optional
        if not rows:
            continue
        for i, n in enumerate(rows):
            v = pins.get(n)
            out.append('| {} | `{}` | {} | {} |'.format(
                label if i == 0 else '',
                n,
                '**{}**'.format(v) if v is not None else '_unset_',
                WHAT.get(n, '') + ((' — ' + note) if (i == 0 and note) else '')))
    out.append('')
    if prof.get('notes'):
        out.append('*{}*'.format(prof['notes']))
        out.append('')
    return out


def build():
    import novaboard as nb
    out = []
    out.append('')
    out.append('*Tables below are generated from the board profiles in '
               '`novaboard.py` — the code is the source of truth, so these cannot '
               'drift. Regenerate with `repo/tools/novad1/gen_wiring.py`.*')
    out.append('')
    for bid in nb.boards():
        out.extend(_table(bid, nb))
    return '\n'.join(out)


def main():
    if not os.path.exists(DOC):
        raise SystemExit('wiring doc not found: ' + DOC)
    text = open(DOC).read()
    if BEGIN not in text or END not in text:
        raise SystemExit('markers missing from ' + DOC +
                         '\nexpected:\n  ' + BEGIN + '\n  ' + END)
    head, rest = text.split(BEGIN, 1)
    _old, tail = rest.split(END, 1)
    new = head + BEGIN + '\n' + build() + '\n' + END + tail
    if '--check' in sys.argv:
        if new != text:
            print('OUT OF DATE: ' + DOC + '  (run gen_wiring.py)')
            return 1
        print('up to date: ' + os.path.basename(DOC))
        return 0
    if new == text:
        print('no change: ' + os.path.basename(DOC))
        return 0
    open(DOC, 'w').write(new)
    print('wrote ' + DOC)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
