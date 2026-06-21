# Desc: Nova D1 wrapper — turns RPCortex into the Nova D1 multi-tool
# File: /Packages/NovaD1/novad1.py
# Version: 0.1.0  (Stage 0 — scaffold)
# Author: dash1101
#
# The Nova D1 isn't its own firmware — it's RPCortex Vela running headless with
# this wrapper on top (see NovaLabs/docs/novad1-dev-plan.md). Stage 0 is the
# foundation that needs no special hardware:
#   novad1 scan    — I2C-scan the bus and identify known Nova D1 modules
#   novad1 setup   — enable headless boot (autonomy) + register the GUI at startup
#   novad1 status  — show what's configured
#   novad1 gui     — launch the Nova GUI (Stage 1 — needs the OLED; stub for now)
#
# Later stages add the OLED driver + menu GUI (Stage 1), MicroSD scripting
# (Stage 2), and per-peripheral driver apps (Stage 3).
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys

# Known Nova D1 devices on the I2C bus (address -> human name).
_I2C_KNOWN = {
    0x3c: 'OLED display (SSD1306/SH1106)',
    0x3d: 'OLED display (alt address)',
    0x68: 'DS3231 real-time clock',
    0x24: 'PN532 NFC/RFID',
    0x48: 'PN532 NFC/RFID (alt)',
}

# Default I2C pins. Builders wire however they like, so these are overridable via
# the registry (Apps.NovaD1_SDA / Apps.NovaD1_SCL) — config-driven, not baked in.
_DEF_SDA = 8
_DEF_SCL = 9


def _w(s):
    sys.stdout.write(s)


def _out():
    """Use RPCortex's colored output if available, else plain writes."""
    try:
        from RPCortex import info, ok, warn, error, multi
        return info, ok, warn, error, multi
    except Exception:
        def p(m, **k): _w(str(m) + '\r\n')
        return p, p, p, p, p


def _i2c_pins():
    sda, scl = _DEF_SDA, _DEF_SCL
    try:
        import regedit
        s = regedit.read('Apps.NovaD1_SDA')
        c = regedit.read('Apps.NovaD1_SCL')
        if s:
            sda = int(s)
        if c:
            scl = int(c)
    except Exception:
        pass
    return sda, scl


def _scan_i2c():
    """Return (found_list, error_or_None). found_list = [(addr, name), ...]."""
    try:
        import machine
    except ImportError:
        return None, 'machine module unavailable (not on-device)'
    sda, scl = _i2c_pins()
    bus = None
    # Try the hardware I2C peripheral, then SoftI2C as a fallback.
    for ctor in ('I2C', 'SoftI2C'):
        try:
            cls = getattr(machine, ctor, None)
            if cls is None:
                continue
            bus = cls(0, scl=machine.Pin(scl), sda=machine.Pin(sda)) \
                if ctor == 'I2C' else cls(scl=machine.Pin(scl), sda=machine.Pin(sda))
            break
        except Exception:
            bus = None
    if bus is None:
        return None, 'could not open I2C on SDA={} SCL={}'.format(sda, scl)
    try:
        addrs = bus.scan()
    except Exception as e:
        return None, 'I2C scan failed: {}'.format(e)
    found = []
    for a in addrs:
        found.append((a, _I2C_KNOWN.get(a, 'unknown device')))
    return found, None


def _scan(info, ok, warn, error, multi):
    info("=== Nova D1 — hardware scan ===", p="NovaD1")
    sda, scl = _i2c_pins()
    multi("  I2C bus: SDA={}  SCL={}  (set Apps.NovaD1_SDA / _SCL to change)".format(sda, scl))
    found, err = _scan_i2c()
    if err:
        warn("I2C: " + err)
        return
    if not found:
        warn("No I2C devices found. Check wiring / pins.")
        return
    has_oled = False
    for a, name in found:
        tag = 'OK ' if name != 'unknown device' else '?  '
        multi("  {} 0x{:02x}  {}".format(tag, a, name))
        if a in (0x3c, 0x3d):
            has_oled = True
    multi("")
    if has_oled:
        ok("Display detected — ready for the Nova GUI (Stage 1).", p="NovaD1")
    else:
        warn("No OLED at 0x3c/0x3d — the Nova GUI needs the display.")
    multi("  (SPI/UART/GPIO modules — CC1101, SX1276, GPS, IR — are detected per-app in Stage 3.)")


def _setup(info, ok, warn, error, multi):
    """Enable headless boot (autonomy) and register the GUI at startup."""
    info("=== Nova D1 — setup (headless boot) ===", p="NovaD1")
    try:
        import regedit
    except Exception:
        error("Registry unavailable — run this on-device.")
        return
    user = regedit.read('Settings.Active_User') or 'root'
    try:
        regedit.save('Settings.Autonomous', user)
        ok("Autonomy enabled — boots straight to the Nova D1 as '{}'.".format(user), p="NovaD1")
    except Exception as e:
        error("Could not enable autonomy: {}".format(e))
        return
    # Register the GUI launch as a startup task (idempotent).
    try:
        path = '/Vela/Registry/startup.cfg'
        line = 'novad1 gui'
        existing = ''
        try:
            with open(path) as f:
                existing = f.read()
        except OSError:
            existing = ''
        if line not in existing:
            with open(path, 'a') as f:
                if existing and not existing.endswith('\n'):
                    f.write('\n')
                f.write(line + '\n')
            ok("Registered 'novad1 gui' to launch at boot.", p="NovaD1")
        else:
            multi("  'novad1 gui' already in startup tasks.")
    except Exception as e:
        warn("Could not register startup task: {}".format(e))
    multi("")
    multi("  Reboot to boot into the Nova D1. (Stage 0: the GUI is a stub until the")
    multi("  OLED driver lands in Stage 1.)  Undo with: autonomy off")


def _status(info, ok, warn, error, multi):
    info("=== Nova D1 — status ===", p="NovaD1")
    try:
        import regedit
        auto = regedit.read('Settings.Autonomous')
        multi("  Headless boot (autonomy): {}".format(auto if auto else 'off'))
        sda, scl = _i2c_pins()
        multi("  I2C pins: SDA={} SCL={}".format(sda, scl))
    except Exception:
        multi("  (registry unavailable)")
    multi("  Stage: 0 (scaffold). Run 'novad1 scan' to probe hardware.")
    multi("  Plan: NovaLabs/docs/novad1-dev-plan.md")


def _gui(info, ok, warn, error, multi):
    warn("Nova GUI is Stage 1 — it needs the OLED + rotary encoder.")
    multi("  Run 'novad1 scan' to confirm the display is wired (0x3c/0x3d).")
    multi("  The OLED driver + menu framework land next; see the dev plan.")


def novad1(args=None):
    info, ok, warn, error, multi = _out()
    sub = (args or '').strip().split(None, 1)
    cmd = sub[0].lower() if sub else 'help'

    if cmd in ('help', '-h', '--help', '?'):
        info("Nova D1 — RPCortex multi-tool wrapper (Stage 0)", p="NovaD1")
        multi("  novad1 scan    Probe the I2C bus for Nova D1 modules")
        multi("  novad1 setup   Enable headless boot + register the GUI at startup")
        multi("  novad1 status  Show what's configured")
        multi("  novad1 gui     Launch the Nova GUI (Stage 1 — needs the OLED)")
        return
    if cmd == 'scan':
        _scan(info, ok, warn, error, multi)
    elif cmd == 'setup':
        _setup(info, ok, warn, error, multi)
    elif cmd == 'status':
        _status(info, ok, warn, error, multi)
    elif cmd == 'gui':
        _gui(info, ok, warn, error, multi)
    else:
        warn("Unknown subcommand '{}'. Try: novad1 help".format(cmd))


if __name__ == '__main__':
    novad1('scan')
