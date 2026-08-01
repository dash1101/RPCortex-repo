# Desc: Nova D1 wrapper — turns RPCortex into the Nova D1 multi-tool
# File: /Packages/NovaD1/novad1.py
# Version: 0.4.0  (rotating-shelf UI, live clock, IRQ encoder, WiFi app, homepage cfg)
# Author: dash1101
#
# The Nova D1 is RPCortex Vela running headless with this wrapper on top
# (NovaLabs/docs/novad1-dev-plan.md). The UI is built on a portable 1-bit canvas
# rendered to an SH1106/SSD1306 OLED (or a PC mock), driven by an EC11 encoder +
# 3 buttons, and is designed to run as a BACKGROUND SERVICE so the serial shell
# stays free. Everything is config-driven + shell-controllable.
#
#   novad1 scan    — I2C-probe for known modules
#   novad1 setup   — enable headless boot (autonomy) + register the GUI
#   novad1 status  — show what's configured
#   novad1 gui     — launch the Nova GUI (on-device; needs the OLED)
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys

# Sibling modules (novacanvas/display/novagui/...) live beside this file.
if '/Packages/NovaD1' not in sys.path:
    sys.path.append('/Packages/NovaD1')

_I2C_KNOWN = {
    0x3c: ('display', 'OLED (SH1106/SSD1306)'),
    0x3d: ('display', 'OLED (alt address)'),
    0x68: ('rtc', 'DS3231 RTC'),
    0x24: ('nfc', 'PN532 NFC/RFID'),
    0x48: ('nfc', 'PN532 NFC/RFID (alt)'),
}

# Pin defaults live in novaboard's board profiles, not here. 3 buttons total
# (encoder SW + 2); on the ESP32-S3 btn2=16 keeps GPIO15 free for the SD CS.
_INPUT_NAMES = ('enc_a', 'enc_b', 'enc_sw', 'btn1', 'btn2')

# Splash + boot-check play ONCE per boot (module globals persist across service
# respawns in the same session, reset on a real reboot — exactly what we want).
_booted = False


def _w(s):
    sys.stdout.write(s)


def _out():
    try:
        from RPCortex import info, ok, warn, error, multi
        return info, ok, warn, error, multi
    except Exception:
        def p(m, **k): _w(str(m) + '\r\n')
        return p, p, p, p, p


from novacore import reg as _reg
import novaboard


def _ensure_dir(p):
    import uos
    try:
        uos.mkdir(p)
    except OSError:
        pass


def _nova_base():
    """Nova's data root: the SD card if mounted, else flash under the OS root."""
    try:
        import sdmgr
        if sdmgr.is_mounted():
            _ensure_dir('/sd/nova')
            return '/sd/nova'
    except Exception:
        pass
    _ensure_dir('/Vela/nova')
    return '/Vela/nova'


def scripts_dir():
    """Where Nova scripts live (SD if present). Created on demand."""
    d = _nova_base() + '/scripts'
    _ensure_dir(d)
    return d


def _i2c_pins():
    return novaboard.pin('sda', 8), novaboard.pin('scl', 9)


def _input_pins():
    pins = {}
    for k in _INPUT_NAMES:
        pins[k] = novaboard.pin(k)
    return pins


def _open_i2c():
    import machine
    sda, scl = _i2c_pins()
    for ctor in ('I2C', 'SoftI2C'):
        cls = getattr(machine, ctor, None)
        if cls is None:
            continue
        try:
            # 1 MHz: the SH1106 handles it, and the framebuffer push (~1 KB/frame)
            # at 1 MHz is ~10ms vs ~100ms at the 100 kHz default — this is what
            # actually makes the UI animate smoothly. SoftI2C is the slow fallback.
            if ctor == 'I2C':
                return cls(0, scl=machine.Pin(scl), sda=machine.Pin(sda), freq=1000000)
            return cls(scl=machine.Pin(scl), sda=machine.Pin(sda), freq=1000000)
        except Exception:
            pass
    return None


def _scan_i2c():
    try:
        import machine  # noqa
    except ImportError:
        return None, 'not on-device'
    bus = _open_i2c()
    if bus is None:
        return None, 'could not open I2C'
    try:
        return bus.scan(), None
    except Exception as e:
        return None, 'scan failed: {}'.format(e)


def _detect_modules():
    """Presence dict for the home menu. I2C modules are confirmed live; SPI/UART
    ones (subghz/lora/gps) come from config flags until Stage-3 probes land."""
    mods = {'display': False, 'rtc': False, 'nfc': False}
    addrs, err = _scan_i2c()
    if addrs:
        for a in addrs:
            ent = _I2C_KNOWN.get(a)
            if ent:
                mods[ent[0]] = True
    # config-declared modules (default on, so the menu shows them)
    for name in ('subghz', 'ir', 'lora', 'gps'):
        mods[name] = (_reg('Apps.NovaD1_MOD_' + name, 'on') != 'off')
    return mods


def _state_provider():
    """Live status for the bar: wifi / battery / time."""
    wifi = 'off'
    try:
        import novawifi
        wifi = novawifi.state()
    except Exception:
        pass
    if wifi != 'connected':                 # reflect OS autoconnect (existing installs)
        try:
            import net
            if net.status().get('connected'):
                wifi = 'connected'
        except Exception:
            pass
    tstr = '--:--'
    try:
        import utime
        off = int(_reg('System.TZ_Offset', 0))
        t = utime.localtime(utime.time() + off * 3600)
        tstr = '{:02d}:{:02d}'.format(t[3], t[4])
    except Exception:
        pass
    pwr = None
    try:
        import novapower
        pwr = novapower.read()
    except Exception:
        pass
    nt = 0
    try:
        import novanotify
        nt = novanotify.count()
    except Exception:
        pass
    sv = False
    try:
        import novastore
        sv = novastore.saving()
    except Exception:
        pass
    return {'wifi': wifi, 'time': tstr, 'power': pwr, 'notify': nt, 'saving': sv}


def _build_ui(kind=None):
    """Construct the NovaUI for on-device use. Returns (ui, err)."""
    try:
        import machine  # noqa
    except ImportError:
        return None, 'needs the device (machine module)'
    bus = _open_i2c()
    if bus is None:
        return None, 'could not open I2C for the display'
    import novacanvas, display, novagui, novainput
    cv = novacanvas.Canvas(128, 64)
    dk = kind or _reg('Apps.NovaD1_Display', 'sh1106')
    disp = display.open_display(bus, kind=dk)
    try:
        disp.contrast(int(_reg('Apps.NovaD1_Contrast', 255)))   # saved brightness
    except Exception:
        pass
    try:
        src = novainput.GpioSource(_input_pins())
    except Exception as e:
        return None, 'input pins: {}'.format(e)
    home = novagui.build_home(_detect_modules())
    hf = lambda: novagui.build_home(_detect_modules())   # for live rebuild
    return novagui.NovaUI(disp, cv, src, _state_provider, home, home_factory=hf), None


# --- subcommands ------------------------------------------------------------
def _scan(info, ok, warn, error, multi):
    info("=== Nova D1 — hardware scan ===", p="NovaD1")
    sda, scl = _i2c_pins()
    multi("  I2C: SDA={} SCL={}  (Apps.NovaD1_SDA / _SCL)".format(sda, scl))
    addrs, err = _scan_i2c()
    if err:
        warn("I2C: " + err)
        return
    if not addrs:
        warn("No I2C devices found. Check wiring / pins.")
        return
    has_oled = False
    for a in addrs:
        ent = _I2C_KNOWN.get(a)
        name = ent[1] if ent else 'unknown device'
        multi("  {} 0x{:02x}  {}".format('OK ' if ent else '?  ', a, name))
        if a in (0x3c, 0x3d):
            has_oled = True
    multi("")
    if has_oled:
        ok("Display detected — ready for the Nova GUI.", p="NovaD1")
    else:
        warn("No OLED at 0x3c/0x3d — the Nova GUI needs the display.")
    multi("  (SPI/UART modules — CC1101, SX1276, GPS — probed per-app in Stage 3.)")


def _setup(info, ok, warn, error, multi):
    info("=== Nova D1 — setup (headless boot) ===", p="NovaD1")
    try:
        import regedit
    except Exception:
        error("Registry unavailable — run on-device.")
        return
    user = _reg('Settings.Active_User', 'root')
    try:
        regedit.save('Settings.Autonomous', user)
        ok("Autonomy on — boots straight to the Nova D1 as '{}'.".format(user), p="NovaD1")
    except Exception as e:
        error("Could not enable autonomy: {}".format(e))
        return
    # Turn OFF the OS boot autoconnect — it blocks boot ~15s when no AP is found
    # (UI won't come up). Nova connects in the BACKGROUND instead (novawifi).
    try:
        regedit.save('Settings.Network_Autoconnect', 'false')
        ok("OS WiFi autoconnect off — Nova connects in the background.", p="NovaD1")
    except Exception:
        pass
    # Register the GUI as a BACKGROUND service so the shell stays free.
    try:
        path = '/Vela/Registry/services.cfg'
        line = 'novad1 gui --bg'
        existing = ''
        try:
            with open(path) as f:
                existing = f.read()
        except OSError:
            pass
        if line not in existing:
            with open(path, 'a') as f:
                if existing and not existing.endswith('\n'):
                    f.write('\n')
                f.write(line + '\n')
            ok("Registered the Nova GUI as a background service.", p="NovaD1")
        else:
            multi("  Nova GUI already registered as a service.")
    except Exception as e:
        warn("Could not register service: {}".format(e))
    # Report the hardware config setup landed on. Previously setup enabled headless
    # boot and stopped, so the first sign of a wrong board or panel was a blank
    # screen after a reboot with nothing pointing at why.
    multi("")
    bid = novaboard.board()
    multi("  Board   : {} ({})".format(bid, novaboard.profile(bid).get('name', bid)))
    multi("  Display : {}".format(_reg('Apps.NovaD1_Display', 'sh1106')))
    sda, scl = _i2c_pins()
    multi("  I2C     : SDA={} SCL={}".format(sda, scl))
    problems = novaboard.check(bid)
    if problems:
        warn("Pinmap problems — fix before rebooting:", p="NovaD1")
        for p in problems:
            multi("    - {}".format(p))
    mods = _detect_modules()
    present = [k for k in mods if mods[k]]
    if present:
        ok("Found on I2C: {}".format(', '.join(present)), p="NovaD1")
    else:
        warn("Nothing answered on I2C — check wiring, or 'd1 pins' if SDA/SCL differ.",
             p="NovaD1")
    multi("")
    multi("  Wrong board or panel?   d1 pins board <id>   d1 display <kind>")
    multi("  Different wiring?       d1 pins  (then: d1 pins set <name> <gpio>)")
    multi("")
    multi("  Reboot to start. The UI runs in the background; the shell stays free.")
    multi("  Undo with: autonomy off   (and: service remove novad1 gui --bg)")


_PIN_HELP = {
    'sda': 'I2C data (OLED, RTC, PN532)', 'scl': 'I2C clock',
    'enc_a': 'encoder A', 'enc_b': 'encoder B', 'enc_sw': 'encoder button',
    'btn1': 'button 1', 'btn2': 'button 2',
    'spi_sck': 'SPI clock (radios/SD)', 'spi_mosi': 'SPI out', 'spi_miso': 'SPI in',
    'sd_cs': 'microSD chip select', 'sd_sck': 'SD clock (split bus)',
    'sd_mosi': 'SD out (split bus)', 'sd_miso': 'SD in (split bus)',
    'cc_cs': 'CC1101 chip select', 'cc_gdo0': 'CC1101 data/GDO0',
    'sx_cs': 'SX1276 chip select', 'sx_rst': 'SX1276 reset',
    'ir_tx': 'IR LED', 'ir_rx': 'IR receiver',
    'gps_tx': 'GPS TX', 'gps_rx': 'GPS RX',
    'buzzer': 'buzzer (PWM)', 'vibe': 'vibration motor', 'led': 'status LED',
    'dht': 'DHT11/22 sensor', 'ibutton': 'iButton / 1-Wire',
    'battery': 'battery ADC (leave unset if unwired)',
    'vbus': 'USB-power sense (optional)',
    'killsw': 'stealth kill switch (active-low, optional)',
}


def _wrapnote(text, width=68):
    """Wrap a profile note so long lines don't run off an 80-column terminal."""
    out = []
    line = ''
    for word in (text or '').split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = (line + ' ' + word) if line else word
    if line:
        out.append(line)
    return out


def _pins(info, ok, warn, error, multi, rest=''):
    """Show and edit the pinmap without touching the registry by hand."""
    parts = (rest or '').split()
    sub = parts[0].lower() if parts else 'list'

    if sub in ('help', '-h', '--help', '?'):
        info("Nova D1 — pins", p="NovaD1")
        multi("  d1 pins                    Show every pin, its value and where it came from")
        multi("  d1 pins set <name> <gpio>  Set a pin  (e.g. d1 pins set ir_tx 12)")
        multi("  d1 pins clear <name>       Undo, back to the board default")
        multi("  d1 pins board              List board profiles")
        multi("  d1 pins board <id>         Switch board  (e.g. d1 pins board rp2350)")
        multi("  d1 pins check              Validate the pinmap for this board")
        return

    if sub == 'board':
        if len(parts) > 1:
            want = parts[1].lower()
            if not novaboard.set_board(want):
                if want in ('auto', 'detect'):
                    error("Could not identify this board. Set it explicitly: "
                          "d1 pins board <id>")
                else:
                    error("Unknown board '{}'. Try: d1 pins board".format(want))
                return
            ok("Board set to '{}'. Reboot, or restart the GUI, to apply."
               .format(novaboard.board()), p="NovaD1")
            _pins(info, ok, warn, error, multi, 'check')
            return
        cur = novaboard.board()
        det = novaboard.detect()
        info("Nova D1 — board profiles", p="NovaD1")
        for bid in novaboard.boards():
            prof = novaboard.profile(bid)
            used, res = novaboard.usable_pins(bid)
            tags = [prof.get('status', '?')]
            if bid == det:
                tags.append('detected')
            multi("  {} {:<11} {:<26} {} pins used  [{}]".format(
                '*' if bid == cur else ' ', bid, prof.get('name', bid), used,
                ', '.join(tags)))
            if prof.get('notes'):
                for ln in _wrapnote(prof['notes']):
                    multi("      {}".format(ln))
        multi("")
        multi("  '*' is active{}.".format(
            "  |  detected: " + det if det else "  |  board not auto-detected"))
        multi("  Switch with: d1 pins board <id>     (or 'auto' to use the detected one)")
        return

    if sub == 'check':
        bid = novaboard.board()
        problems = novaboard.check(bid)
        if not problems:
            ok("Pinmap for '{}' looks consistent.".format(bid), p="NovaD1")
        else:
            warn("Pinmap problems on '{}':".format(bid), p="NovaD1")
            for p in problems:
                multi("  - {}".format(p))
        return

    if sub == 'set':
        if len(parts) < 3:
            error("Usage: d1 pins set <name> <gpio>")
            return
        name = parts[1].lower()
        if name not in novaboard.names():
            error("Unknown pin '{}'. Run 'd1 pins' for the list.".format(name))
            return
        # Read the value in effect BEFORE writing — reporting the board default here
        # would lie about a pin that was already overridden.
        prev = novaboard.pin(name)
        if not novaboard.set_pin(name, parts[2]):
            error("'{}' is not a valid pin number.".format(parts[2]))
            return
        ok("{} = {}  (was {})".format(name, novaboard.pin(name),
                                      'unset' if prev is None else prev), p="NovaD1")
        multi("  Undo with: d1 pins clear {}".format(name))
        return

    if sub in ('clear', 'unset', 'reset'):
        if len(parts) < 2:
            error("Usage: d1 pins clear <name>")
            return
        name = parts[1].lower()
        novaboard.clear_pin(name)
        v = novaboard.pin(name)
        ok("{} back to the board default: {}".format(name, 'unset' if v is None else v),
           p="NovaD1")
        return

    if sub != 'list':
        warn("Unknown option '{}'. Try: d1 pins help".format(sub))
        return

    # Default view: every pin, its value, and whether it came from the board profile
    # or an override. Being explicit about the source is the whole point — otherwise
    # there is no way to tell a default from something you set months ago.
    bid = novaboard.board()
    prof = novaboard.profile(bid)
    info("Nova D1 — pins on '{}' ({})".format(bid, prof.get('name', bid)), p="NovaD1")
    multi("  NAME       GPIO  SOURCE    WHAT")
    over = 0
    for name in novaboard.names(bid):
        v = novaboard.pin(name)
        src = novaboard.source(name)
        if src == 'override':
            over += 1
        multi("  {:<10} {:>4}  {:<8}  {}".format(
            name, '-' if v is None else v, src, _PIN_HELP.get(name, '')))
    multi("")
    multi("  {} pin(s) overridden; the rest come from the board profile."
          .format(over) if over else "  All pins are board defaults.")
    multi("  Change one with: d1 pins set <name> <gpio>")
    problems = novaboard.check(bid)
    if problems:
        multi("")
        warn("{} problem(s) found — run 'd1 pins check'".format(len(problems)), p="NovaD1")


def _display_cmd(info, ok, warn, error, multi, rest=''):
    """Pick the OLED panel. 'auto' stays SH1106 — the panels share an I2C address
    and cannot be told apart reliably, so this is a choice, never a guess."""
    import display
    want = (rest or '').strip().lower()
    cur = _reg('Apps.NovaD1_Display', 'sh1106')
    kinds = [k for k in display.KINDS if k != 'mock']
    if not want:
        info("Nova D1 — display", p="NovaD1")
        for k in kinds:
            multi("  {} {}".format('*' if k == cur else ' ', k))
        multi("")
        multi("  '*' is active. Set with: d1 display <kind>")
        multi("  sh1106  1.3\" 128x64 (shipping)   ssd1306  0.96\" 128x64")
        multi("  ssd1309 2.42\" 128x64")
        return
    if want not in kinds:
        error("Unknown panel '{}'. One of: {}".format(want, ', '.join(kinds)))
        return
    try:
        import regedit
        regedit.save('Apps.NovaD1_Display', want)
        ok("Display set to '{}'. Restart the GUI to apply.".format(want), p="NovaD1")
    except Exception as e:
        error("Could not save: {}".format(e))


def _pin(info, ok, warn, error, multi, rest=''):
    """Show / set / CLEAR the UI lock PIN. Clearing previously meant reinstalling
    the package, because the only way in was the on-screen 'Set PIN' entry."""
    parts = (rest or '').split()
    sub = parts[0].lower() if parts else 'status'
    cur = _reg('Apps.NovaD1_PIN', '')

    if sub in ('clear', 'off', 'remove', 'reset'):
        try:
            import regedit
            regedit.save('Apps.NovaD1_PIN', '')
            ok("UI PIN cleared — the lock screen is off.", p="NovaD1")
        except Exception as e:
            error("Could not clear the PIN: {}".format(e))
        return
    if sub == 'set':
        if len(parts) < 2 or not parts[1].isdigit() or len(parts[1]) != 6:
            error("Usage: d1 pin set <6 digits>   (or: d1 pin clear)")
            return
        try:
            import regedit
            regedit.save('Apps.NovaD1_PIN', parts[1])
            ok("UI PIN set.", p="NovaD1")
        except Exception as e:
            error("Could not set the PIN: {}".format(e))
        return
    info("Nova D1 — UI lock PIN", p="NovaD1")
    multi("  PIN: {}".format('set' if cur else 'not set'))
    multi("  d1 pin set <6 digits> | clear")


def _wardrive(info, ok, warn, error, multi, rest=''):
    """One-shot wardriving scan from the shell: scan WiFi, tag with GPS if a fix is
    available, append new APs to the WiGLE CSV. The GUI Wardrive app does continuous
    logging; this is a quick manual pass / status check."""
    import novawardrive as wd
    parts = (rest or '').split()
    sub = parts[0].lower() if parts else 'scan'

    base, on_sd = wd.log_dir()
    if sub == 'status':
        info("Wardrive", p="NovaD1")
        multi("  Log dir : {}  ({})".format(base, 'SD card' if on_sd else 'onboard flash'))
        okw, why = wd.can_write(on_sd)
        multi("  Writable: {}{}".format('yes' if okw else 'NO', '  - ' + why if why else ''))
        if not on_sd:
            multi("  Tip: an SD card is recommended for wardriving (many writes).")
        return

    okw, why = wd.can_write(on_sd)
    if not okw:
        error(why or "Storage full — cannot log.")
        return
    if why:
        warn(why, p="NovaD1")

    info("Scanning WiFi...", p="NovaD1")
    aps = wd.scan_now()
    if not aps:
        warn("No networks found (or WiFi unavailable).", p="NovaD1")
        return
    # GPS is optional for a shell one-shot; log without coords.
    ts = ''
    try:
        import utime
        t = utime.localtime()
        ts = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(t[0], t[1], t[2], t[3], t[4], t[5])
    except Exception:
        pass
    try:
        import uos
        try:
            uos.mkdir(base)
        except OSError:
            pass
        path = base + '/wardrive.csv'
        newfile = not _file_there(path)
        f = open(path, 'a')
        if newfile:
            f.write(wd.wigle_header())
        sess = wd.Session()
        rows = sess.add(aps, ts)
        for r in rows:
            f.write(r)
        f.close()
        ok("Logged {} networks -> {}".format(len(rows), path), p="NovaD1")
    except Exception as e:
        error("Log failed: {}".format(e))


def _file_there(path):
    try:
        import uos
        uos.stat(path)
        return True
    except OSError:
        return False


def _fav(info, ok, warn, error, multi, rest=''):
    """Manage the home favorites bar — pinned apps launch from the top of the home."""
    parts = (rest or '').split()
    sub = parts[0].lower() if parts else 'list'
    favs = [k.strip() for k in _reg('Apps.NovaD1_Favorites', '').split(',') if k.strip()]

    def _save():
        try:
            import regedit
            regedit.save('Apps.NovaD1_Favorites', ','.join(favs))
        except Exception:
            pass
        try:
            import novagui                     # rebuild the home live, no reboot
            if hasattr(novagui, '_mark_home_dirty'):
                novagui._mark_home_dirty()
        except Exception:
            pass

    if sub in ('list', ''):
        info("Home favorites", p="NovaD1")
        multi("  Pinned: {}".format(', '.join(favs) if favs else '(none)'))
        multi("  d1 fav add <appkey> | remove <appkey>   (see keys: d1 apps)")
        return
    if sub == 'add':
        if len(parts) < 2:
            error("Usage: d1 fav add <appkey>")
            return
        k = parts[1]
        if k in favs:
            multi("  '{}' is already pinned.".format(k))
            return
        favs.append(k)
        _save()
        ok("Pinned '{}' to the home.".format(k), p="NovaD1")
        return
    if sub in ('remove', 'rm', 'del', 'unpin'):
        if len(parts) < 2:
            error("Usage: d1 fav remove <appkey>")
            return
        k = parts[1]
        if k not in favs:
            multi("  '{}' isn't pinned.".format(k))
            return
        favs.remove(k)
        _save()
        ok("Unpinned '{}'.".format(k), p="NovaD1")
        return
    warn("Usage: d1 fav list | add <appkey> | remove <appkey>")


def _stealth(info, ok, warn, error, multi, rest=''):
    """Incognito / kill switch: take every radio down instantly, or restore."""
    import novastealth
    parts = (rest or '').strip().lower().split()
    sub = parts[0] if parts else 'status'

    if sub in ('mac', 'randommac'):
        val = parts[1] if len(parts) > 1 else ''
        if val in ('on', 'off'):
            try:
                import regedit
                regedit.save('Apps.NovaD1_RandomMAC', 'on' if val == 'on' else 'off')
                ok("Anti-fingerprint MAC randomisation {}.".format(val), p="NovaD1")
            except Exception as e:
                error("Could not save: {}".format(e))
        else:
            multi("  Random MAC: {}".format('on' if novastealth.mac_random_enabled() else 'off'))
            multi("  incognito mac on | off")
        return

    if sub in ('on', 'kill', 'panic'):
        down = novastealth.kill_all()
        ok("INCOGNITO ON — silenced: {}".format(
            ', '.join(down) if down else '(no active radios found)'), p="NovaD1")
        multi("  The device is dark — nothing transmits or listens on any band.")
        multi("  Leave with: incognito off")
        return

    if sub in ('off', 'restore'):
        novastealth.restore()
        ok("Incognito off — radios may be re-enabled as needed.", p="NovaD1")
        return

    if sub == 'toggle':
        now = novastealth.toggle()
        ok("Incognito {}.".format('ON — radios killed' if now else 'off'), p="NovaD1")
        return

    if sub == 'status':
        info("=== Nova D1 — stealth ===", p="NovaD1")
        multi("  Incognito : {}".format(
            'ON — radios killed' if novastealth.active() else 'off'))
        multi("  Random MAC: {}".format(
            'on' if novastealth.mac_random_enabled() else 'off'))
        pin = novastealth.switch_pin()
        multi("  Kill switch pin: {}".format(pin if pin is not None else 'not set'))
        multi("")
        multi("  incognito on      kill ALL radios now (WiFi/BLE/LoRa/sub-GHz/NFC)")
        multi("  incognito off     leave stealth")
        multi("  incognito toggle  flip it")
        multi("  incognito mac on  randomise MACs to resist fingerprinting")
        multi("  Wire a switch:  d1 pins set killsw <gpio>  (active-low)")
        return

    warn("Usage: incognito on | off | toggle | status | mac on|off")


def _status(info, ok, warn, error, multi):
    info("=== Nova D1 — status ===", p="NovaD1")
    bid = novaboard.board()
    multi("  Board: {} ({})".format(bid, novaboard.profile(bid).get('name', bid)))
    multi("  Headless boot: {}".format(_reg('Settings.Autonomous', 'off')))
    sda, scl = _i2c_pins()
    multi("  I2C: SDA={} SCL={}   Display: {}".format(sda, scl, _reg('Apps.NovaD1_Display', 'sh1106')))
    p = _input_pins()
    multi("  Encoder A/B/SW: {}/{}/{}   Buttons: {}/{}".format(
        p['enc_a'], p['enc_b'], p['enc_sw'], p['btn1'], p['btn2']))
    over = [n for n in novaboard.names(bid) if novaboard.source(n) == 'override']
    multi("  Pin overrides: {}".format(', '.join(sorted(over)) if over else 'none'))
    # Be honest: display/rtc/nfc are actually PROBED on I2C; subghz/ir/lora/gps are
    # config flags (default on), NOT hardware-detected. Reporting them together as
    # "Detected" claimed radios that weren't even wired.
    addrs, scan_err = _scan_i2c()
    probed = []
    if addrs:
        seen = set()
        for a in addrs:
            ent = _I2C_KNOWN.get(a)
            if ent and ent[0] not in seen:
                probed.append(ent[0]); seen.add(ent[0])
    multi("  Detected on I2C : {}".format(
        ', '.join(probed) if probed else (scan_err or 'none')))
    enabled = [n for n in ('ir', 'subghz', 'lora', 'gps')
               if _reg('Apps.NovaD1_MOD_' + n, 'on') != 'off']
    multi("  Enabled (unprobed): {}   [config flags — not a hardware check]".format(
        ', '.join(enabled) if enabled else 'none'))
    home = _reg('Apps.NovaD1_Home')
    multi("  Home apps: {}".format(home if home else 'all (default)'))
    problems = novaboard.check(bid)
    if problems:
        warn("{} pinmap problem(s) — run 'd1 pins check'".format(len(problems)), p="NovaD1")
    multi("  Setup guide: novalabs.app/d1   (or 'd1 pins' / 'd1 help' here)")


def _apps(info, ok, warn, error, multi, rest=''):
    """Homepage config: choose which apps show on the shelf (Apps.NovaD1_Home)."""
    import novagui
    novagui._load_cat_overrides()
    allapps = [(k, l) for k, l, _f in novagui._all_apps()]
    raw = _reg('Apps.NovaD1_Home')
    enabled = [k.strip() for k in raw.split(',') if k.strip()] if raw else None
    parts = rest.split(None, 1)
    act = parts[0].lower() if parts else 'list'
    key = parts[1].strip() if len(parts) > 1 else ''
    cur = enabled if enabled is not None else [k for k, _l in allapps]
    valid = {k for k, _l in allapps}
    if act in ('show', 'add', 'hide', 'remove', 'rm'):
        if key not in valid:
            error("Unknown app '{}'. See: novad1 apps".format(key)); return
        if act in ('show', 'add'):
            if key not in cur:
                cur.append(key)
        else:
            cur = [k for k in cur if k != key] or cur
        try:
            import regedit
            regedit.save('Apps.NovaD1_Home', ','.join(cur))
        except Exception as e:
            error("Could not save: {}".format(e)); return
        ok("Home apps updated. Re-open the GUI to see it.", p="NovaD1")
        return
    if act == 'reset':
        try:
            import regedit
            regedit.save('Apps.NovaD1_Home', '')
        except Exception:
            pass
        ok("Home reset to all apps.", p="NovaD1"); return
    if act == 'cat':
        cp = key.split(None, 1)
        appkey = cp[0].strip() if cp and cp[0].strip() else ''
        catname = cp[1].strip() if len(cp) > 1 else ''
        if not appkey:
            error("Usage: novad1 apps cat <key> <Wireless|Sensors|Tools|System|auto>")
            return
        if appkey not in valid and not appkey.startswith('script_'):
            error("Unknown app '{}'. See: novad1 apps".format(appkey)); return
        canon = {c.lower(): c for c in novagui._CATEGORIES}
        if catname.lower() in ('auto', 'default', 'clear', ''):
            novagui._set_cat_override(appkey, None)
            ok("'{}' folder reset to its default.".format(appkey), p="NovaD1")
        elif catname.lower() in canon:
            novagui._set_cat_override(appkey, canon[catname.lower()])
            ok("'{}' moved to {}.".format(appkey, canon[catname.lower()]), p="NovaD1")
        else:
            error("Folder must be Wireless, Sensors, Tools, System, or auto.")
        return
    info("=== Nova D1 — home apps ===", p="NovaD1")
    for k, l in allapps:
        on = (enabled is None) or (k in enabled)
        multi("  [{}] {:10} {:8} {}".format('x' if on else ' ', k, novagui._app_category(k), l))
    multi("")
    multi("  novad1 apps show <key> | hide <key> | cat <key> <folder> | reset")


def _save_err(msg):
    try:
        import regedit
        regedit.save('Apps.NovaD1_LastError', str(msg)[:80])
    except Exception:
        pass


def _clear_err():
    try:
        import regedit
        regedit.save('Apps.NovaD1_LastError', '')
    except Exception:
        pass


def _nlog(msg):
    try:
        import novalog
        novalog.log(msg)
    except Exception:
        pass


def set_web(on):
    """Start/stop the web control panel as a background service (async shell)."""
    try:
        lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
        if lp is None:
            return
        if on and hasattr(lp, 'register_service'):
            import novaweb
            lp.register_service('novaweb', novaweb.serve)
            _nlog('web panel enabled')
        elif not on and hasattr(lp, 'unregister_service'):
            lp.unregister_service('novaweb')
            _nlog('web panel disabled')
    except Exception:
        pass


def _seed_scripts():
    """Write a couple of example button-grid scripts on first run so the Scripts
    app has working content + shows the format. Only if no scripts exist yet."""
    try:
        import novastore
        if novastore.list_codes('scripts'):
            return
        demo = ("# Nova D1 demo remote — these work out of the box.\n"
                "title: Demo\n"
                "Sysinfo = run sysinfo\n"
                "Free RAM = run meminfo\n"
                "Notify = notify hello from Nova\n"
                "LoRa Ping = lora ping\n")
        novastore.save_code('scripts', 'demo.txt', demo)
        tv = ("# IR remote template — record buttons into tv.ir first (IR app),\n"
              "# then each line fires a saved signal by name.\n"
              "title: TV\n"
              "Power = ir tv.ir Power\n"
              "Vol+ = ir tv.ir Vol_up\n"
              "Vol- = ir tv.ir Vol_dn\n"
              "Input = ir tv.ir Input\n")
        novastore.save_code('scripts', 'tv_remote.txt', tv)
        _nlog('seeded example scripts')
    except Exception:
        pass


def _boot_or_recover(ui, novagui, fresh=True):
    """Initial screen stack. On a FRESH GUI start the splash ALWAYS plays (100% of
    the time) — even after a stored error, which now shows AFTER the splash. A
    crash-respawn (fresh=False) just flashes the error, no re-splash."""
    global _booted
    last = _reg('Apps.NovaD1_LastError')
    if last:
        _clear_err()
    if fresh:
        _booted = True
        try:
            import novasound
            novasound.chime()          # boot chime (gated + try-excepted inside)
        except Exception:
            pass
        ui.stack = novagui.make_boot_stack(ui.stack[0])     # [home, Splash]
        if last:
            ui.stack.insert(1, novagui.ErrorScreen(last))   # seen after the splash
        if _reg('Apps.NovaD1_PIN'):            # gate the UI behind the PIN if set
            ui.stack.insert(1, novagui.PinScreen('verify'))
        _nlog('Nova D1 GUI started')
    elif last:
        ui.stack.append(novagui.ErrorScreen(last))


async def _gui_service():
    """Self-healing background GUI: rebuilds + relaunches on crash (with backoff),
    stores the error and flashes it on the next start. Catches everything itself
    so it's the SINGLE respawn source (the OS service guard never sees a crash).

    Runs as a BACKGROUND service sharing the event loop with the serial shell, so
    it must NEVER write to stdout/serial (that would flood the shell) — all
    diagnostics go to the Nova flash log. It also waits a short, configurable
    settle delay on first start so the shell + USB-CDC come up first."""
    import asyncio
    import novagui
    first = True
    crashes = 0
    while True:
        ui, err = _build_ui()
        if err:
            _save_err('start: ' + err)        # unrecoverable (no display) -> stop
            _nlog('GUI start failed: ' + err)
            return
        try:                                  # background WiFi manager (once)
            import novawifi
            if not novawifi._started:
                asyncio.create_task(novawifi.manager())
        except Exception:
            pass
        try:                                  # background LoRa messaging (once; self-
            import novamsg                    # disables if no SX1276 answers)
            if not novamsg._started:
                asyncio.create_task(novamsg.manager())
        except Exception:
            pass
        try:                                  # background code -> SD backup mover (once)
            import novastore
            if not getattr(novastore, '_mover_on', False):
                novastore._mover_on = True
                asyncio.create_task(novastore.backup_mover())
        except Exception:
            pass
        fresh = first                         # True only on the first launch (not respawns)
        if first and _reg('Apps.NovaD1_Web', 'off') == 'on':
            set_web(True)                     # auto-host the control panel
        if first:
            first = False
            try:
                import novartc
                novartc.boot_sync()           # DS3231 -> RTC if present (offline time)
            except Exception:
                pass
            _seed_scripts()                   # example button-grid scripts (once)
            # Screen ON immediately with the splash — ALWAYS on a fresh start, so it
            # shows 100% of the time (a stored error now shows after it, not instead).
            try:
                import novasplash
                novasplash.draw(ui.canvas, 0.5)
                ui.display.show(ui.canvas)
            except Exception:
                pass
            # Optional extra settle hold (default 0 — the splash already gives ~1.5s
            # of light loop activity, covering the boot work, before any heavy probe).
            try:
                d = int(_reg('Apps.NovaD1_Boot_Delay', 0))
            except (TypeError, ValueError):
                d = 0
            if d > 0:
                try:
                    await asyncio.sleep_ms(d)
                except Exception:
                    pass
        _boot_or_recover(ui, novagui, fresh)
        try:
            await ui.run_async()
            if getattr(ui, '_stop', False):
                return                        # intentional stop -> done, no respawn
        except Exception as e:
            crashes += 1
            _save_err('{}: {}'.format(type(e).__name__, e))
            _nlog('GUI crash #{}: {}'.format(crashes, e))   # log only — never serial
            if crashes >= 5:
                _nlog('GUI gave up after 5 crashes')
                return                        # stop respawning -> can't flood/spin
            try:
                await asyncio.sleep_ms(2000)  # backoff, then rebuild + relaunch
            except Exception:
                pass


def _web(info, ok, warn, error, multi, rest=''):
    r = rest.strip().lower()
    if r in ('on', 'start'):
        try:
            import regedit
            regedit.save('Apps.NovaD1_Web', 'on')
        except Exception:
            pass
        set_web(True)
        import novaweb
        ok("Web panel on — open http://{}/ from your phone.".format(novaweb._ip()), p="NovaD1")
    elif r in ('off', 'stop'):
        try:
            import regedit
            regedit.save('Apps.NovaD1_Web', 'off')
        except Exception:
            pass
        set_web(False)
        ok("Web panel off.", p="NovaD1")
    else:
        import novaweb
        multi("  Web panel: {}".format(_reg('Apps.NovaD1_Web', 'off')))
        multi("  URL: http://{}:{}/".format(novaweb._ip(), _reg('Apps.NovaD1_Web_Port', 80)))
        multi("  PIN: {}".format('set' if _reg('Apps.NovaD1_Web_PIN', '') else 'none (LAN open)'))
        multi("  novad1 web on | off   (PIN: reg set Apps.NovaD1_Web_PIN <pin>)")


def _notify(info, ok, warn, error, multi, rest=''):
    text = rest.strip()
    if not text:
        warn("Usage: novad1 notify <text>")
        return
    try:
        import novanotify
        if novanotify.notify(text):
            ok("Notification pushed to the Nova UI.", p="NovaD1")
        else:
            warn("Notifications are off (settings: Notify).")
    except Exception as e:
        error("notify failed: {}".format(e))


def _perf(info, ok, warn, error, multi):
    info("=== Nova D1 — perf ===", p="NovaD1")
    import gc
    multi("  free RAM: {} KB".format(gc.mem_free() // 1024))
    try:
        import novagui
        p = novagui.perf_stats()
        if p:
            multi("  GUI render: {} us (peak since last: {} us)".format(
                p['render_us'], p['render_max_us']))
            multi("  renders: {}   screen-dimmed: {}".format(p['shows'], p['dimmed']))
            # Screen-timeout diagnostics (why isn't it shutting off?):
            lvl = {0: '0 active', 1: '1 dimmed', 2: '2 off'}.get(p.get('level'), p.get('level'))
            multi("  screen level: {}   idle: {} s".format(lvl, p.get('idle_s')))
            multi("  timers(s): dim={} off={} lock={}".format(
                p.get('dim_s'), p.get('off_s'), p.get('lock_s')))
            multi("  -> sit idle and re-run: if idle resets to ~0 each time, phantom")
            multi("     input is keeping it awake; if off=0 the timer is disabled.")
        else:
            multi("  GUI not running (open the Nova GUI to measure).")
    except Exception as e:
        warn("perf: {}".format(e))
    multi("  (A render that blocks > ~15ms stutters the shell. Spin the encoder /")
    multi("   open an app, then re-run to read the peak.)")


def _fire(info, ok, warn, error, multi, arg):
    """Fire a saved code by category+name — one entry point for the shell, scripts,
    and the web panel (run a code without opening its GUI app)."""
    parts = arg.split(None, 1)
    if len(parts) < 2:
        multi("  Usage: novad1 fire <cat> <name>")
        multi("    cat: ir | subghz | lora    e.g. novad1 fire ir tv.ir")
        return
    cat = parts[0].strip().lower()
    name = parts[1].strip()
    import novastore
    txt = novastore.read_code(cat, name)
    if txt is None:
        error("No such code: {}/{}".format(cat, name), p="NovaD1")
        return
    fired = False
    try:
        if cat == 'ir':
            import novair
            sigs = novair.parse_flipper(txt)
            for sig in sigs:
                _n, fr, du, times = sig
                novair.replay(times, fr, du)
            fired = bool(sigs)
        elif cat == 'subghz':
            import novacc
            if not novacc.present():
                error("Sub-GHz radio (CC1101) not detected — check the module.", p="NovaD1")
                return
            fired = novacc.fire_text(txt)
        elif cat == 'lora':
            import novamsg
            if not novamsg.present():
                error("LoRa radio (SX1276) not detected — check the module.", p="NovaD1")
                return
            novamsg.send(txt.strip())
            fired = True
        else:
            error("Can't fire category '{}' (ir|subghz|lora).".format(cat), p="NovaD1")
            return
    except Exception as e:
        error("fire error: {}".format(e), p="NovaD1")
        return
    if fired:
        ok("Fired {}/{}".format(cat, name), p="NovaD1")
    else:
        warn("Nothing fired (empty/unsupported code).", p="NovaD1")


def _ble(info, ok, warn, error, multi, arg):
    """BLE: scan nearby devices, or ping your phone with a pairing popup. Jamming
    isn't possible on this radio (and is illegal); this is bounded own-device use."""
    import novable
    if not novable.available():
        error("BLE not available on this board.", p="NovaD1")
        return
    parts = arg.split()
    sub = parts[0].lower() if parts else 'scan'
    if sub == 'scan':
        info("=== BLE scan (5s) ===", p="NovaD1")
        devs = novable.scan(5000)
        if not devs:
            multi("  (none found)")
        for d in devs[:25]:
            multi("  {:>4} dBm  {}  {}".format(d['rssi'], d['mac'], (d['name'] or '')[:16]))
        multi("  {} device(s).".format(len(devs)))
    elif sub == 'ping':
        platform = parts[1].lower() if len(parts) > 1 else 'apple'
        model = parts[2].lower() if len(parts) > 2 else None
        info("Pinging {} ~8s — watch YOUR phone for the popup...".format(platform), p="NovaD1")
        m = novable.ping(platform, model, 8)
        if m:
            ok("Ping sent (model '{}'). Point it at your own phone.".format(m), p="NovaD1")
        else:
            warn("Ping failed.", p="NovaD1")
    elif sub == 'stop':
        novable.stop()
        ok("BLE advertising stopped.", p="NovaD1")
    else:
        multi("  Usage: novad1 ble scan | ping [apple|android] [model] | stop")


def _store(info, ok, warn, error, multi, arg):
    """Browse + install Nova apps from the online store (repo/novad1-apps). The
    shell/scripting route to the same catalogue the App Store screen uses — so the
    store isn't GUI-only. Installed apps land on the home, auto-categorised."""
    import novaappstore
    parts = arg.split(None, 1)
    sub = parts[0].strip().lower() if parts and parts[0].strip() else 'list'
    if sub in ('list', 'ls'):
        info("Fetching the app store (WiFi + HTTPS)...", p="NovaD1")
        apps = novaappstore.fetch_index()
        if apps is None:
            error("Couldn't reach the store. Check WiFi is connected.", p="NovaD1")
            return
        installed = novaappstore.installed_names()
        info("=== Nova D1 app store ({} apps) ===".format(len(apps)), p="NovaD1")
        for a in apps:
            mark = '  [installed]' if (a.get('dir', '') + '.txt') in installed else ''
            multi("  {:<13} {:<9} {}{}".format(
                (a.get('name') or '?')[:13], (a.get('category') or '')[:9],
                (a.get('desc') or '')[:30], mark))
        multi("  novad1 store install <name>")
    elif sub == 'install':
        name = parts[1].strip() if len(parts) > 1 else ''
        if not name:
            error("Usage: novad1 store install <name>", p="NovaD1")
            return
        apps = novaappstore.fetch_index()
        if apps is None:
            error("Couldn't reach the store. Check WiFi is connected.", p="NovaD1")
            return
        low = name.lower()
        app = None
        for a in apps:
            if (a.get('name') or '').lower() == low or (a.get('dir') or '').lower() == low:
                app = a
                break
        if not app:
            error("No app '{}'. Run 'novad1 store' to see the list.".format(name), p="NovaD1")
            return
        info("Installing {}...".format(app.get('name')), p="NovaD1")
        entry = novaappstore.install(app)
        if entry:
            ok("Installed '{}'. It's on the home now.".format(app.get('name')), p="NovaD1")
        else:
            error("Install failed (download or save error).", p="NovaD1")
    else:
        multi("  novad1 store [list] | install <name>")


def _logs(info, ok, warn, error, multi, rest=''):
    import novalog
    r = rest.strip().lower()
    if r == 'clear':
        novalog.clear()
        ok("Nova log cleared.", p="NovaD1")
        return
    n = int(r) if r.isdigit() else 40
    lines = novalog.tail(n)
    info("=== Nova D1 — event log (last {}) ===".format(n), p="NovaD1")
    if not lines:
        multi("  (empty)")
    for l in lines:
        multi("  " + l)


_SVC_NAME = 'novad1'


def _svc(info, ok, warn, error, multi, rest=''):
    """Manage the Nova GUI background service: start / stop / restart / refresh.
    'refresh' restarts it so it re-reads the pin config (I2C + inputs) — apply a
    'd1 pins set' change without a full reboot."""
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
    if lp is None or not hasattr(lp, 'register_service'):
        error("Service engine unavailable — the async shell isn't active.")
        return
    running = lp.service_running(_SVC_NAME) if hasattr(lp, 'service_running') else False
    sub = (rest or '').strip().lower()

    if sub in ('', 'status'):
        multi("  Nova GUI service: {}".format('running' if running else 'stopped'))
        multi("  d1 service start | stop | restart | status")
        multi("  d1 refresh   reload pins (restart the service)")
        return
    if sub == 'stop':
        lp.unregister_service(_SVC_NAME)
        ok("Nova GUI service stopped.", p="NovaD1")
        return
    if sub == 'start':
        if running:
            multi("  Nova GUI service already running.")
            return
        lp.register_service(_SVC_NAME, _gui_service)
        ok("Nova GUI service started.", p="NovaD1")
        return
    if sub in ('restart', 'refresh', 'reload'):
        lp.unregister_service(_SVC_NAME)          # cancel the running instance
        lp.register_service(_SVC_NAME, _gui_service)   # respawn — re-reads pins
        ok("Nova GUI service {} — pins reloaded.".format(
            'restarted' if sub == 'restart' else 'refreshed'), p="NovaD1")
        return
    warn("Usage: d1 service start | stop | restart | status   (or: d1 refresh)")


def _gui(info, ok, warn, error, multi, bg=False):
    if bg:
        try:
            lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
            if lp and hasattr(lp, 'register_service'):
                lp.register_service('novad1', _gui_service)
                ok("Nova GUI started in the background (auto-relaunch on crash).", p="NovaD1")
                return
            warn("Async shell not active; running foreground instead.")
        except Exception as e:
            warn("Background start failed ({}); running foreground.".format(e))
    ui, err = _build_ui()
    if err:
        warn("Nova GUI: " + err)
        multi("  (Concept UI renders on the PC mock; on-panel needs the SH1106.)")
        return
    import novagui
    _boot_or_recover(ui, novagui)
    info("Nova GUI — BACK from home exits.", p="NovaD1")
    ui.run()


def novad1(args=None):
    info, ok, warn, error, multi = _out()
    parts = (args or '').strip().split(None, 1)
    cmd = parts[0].lower() if parts else 'help'
    rest = parts[1].strip().lower() if len(parts) > 1 else ''

    if cmd in ('help', '-h', '--help', '?'):
        info("Nova D1 — RPCortex multi-tool wrapper", p="NovaD1")
        multi("  novad1 setup       Headless boot + register the GUI as a service")
        multi("  novad1 scan        Probe the I2C bus for Nova D1 modules")
        multi("  novad1 status      Show what's configured")
        multi("  novad1 pins        Show/edit the pinmap (pins set <name> <gpio>)")
        multi("  novad1 display <k> Panel: sh1106 | ssd1306 | ssd1309")
        multi("  incognito on|off   Kill ALL radios instantly (stealth mode)")
        multi("  novad1 wardrive    WiFi survey -> WiGLE CSV (scan|status)")
        multi("  novad1 pin ...      UI lock PIN: set <6 digits> | clear")
        multi("  novad1 fav ...      Pin apps to the home favorites bar")
        multi("  novad1 service ... GUI service: start|stop|restart|status")
        multi("  novad1 refresh     Reload pins (restart the GUI service)")
        multi("  novad1 apps ...    Choose which apps show on the home")
        multi("  novad1 style g|m   Home layout: gallery (icons) or menu (list)")
        multi("  novad1 logs [n]    Show the Nova event log (or 'clear')")
        multi("  novad1 notify <t>  Push a notification to the Nova UI")
        multi("  novad1 fire <cat> <name>  Fire a saved code (ir|subghz|lora)")
        multi("  novad1 ble scan|ping [apple|android]  Scan / ping your phone")
        multi("  novad1 store       Browse + install apps (store install <name>)")
        multi("  novad1 web on|off  Phone control panel over WiFi")
        multi("  novad1 wifiprobe   Check if this firmware can capture 802.11 (pcap)")
        multi("  novad1 gui [--bg]  Launch the Nova GUI (--bg = background service)")
        multi("")
        multi("  Wiring is per-board: 'novad1 pins' lists every pin and where its")
        multi("  value came from. No registry editing needed.")
        return
    if cmd == 'scan':
        _scan(info, ok, warn, error, multi)
    elif cmd == 'setup':
        _setup(info, ok, warn, error, multi)
    elif cmd == 'status':
        _status(info, ok, warn, error, multi)
    elif cmd in ('pins', 'pin'):
        rest_cs = (args or '').strip().split(None, 1)
        _pins(info, ok, warn, error, multi, rest_cs[1] if len(rest_cs) > 1 else '')
    elif cmd in ('display', 'screen'):
        _display_cmd(info, ok, warn, error, multi, rest)
    elif cmd in ('incognito', 'stealth', 'panic'):
        _stealth(info, ok, warn, error, multi, rest)
    elif cmd in ('service', 'svc'):
        _svc(info, ok, warn, error, multi, rest)
    elif cmd in ('fav', 'favorite', 'favorites'):
        rest_cs = (args or '').strip().split(None, 1)
        _fav(info, ok, warn, error, multi, rest_cs[1] if len(rest_cs) > 1 else '')
    elif cmd in ('wardrive', 'wardriving'):
        _wardrive(info, ok, warn, error, multi, rest)
    elif cmd == 'pin':
        _pin(info, ok, warn, error, multi, rest)
    elif cmd in ('refresh', 'reload'):
        _svc(info, ok, warn, error, multi, 'refresh')
    elif cmd == 'apps':
        # keep original case for keys
        rest_cs = (args or '').strip().split(None, 1)
        _apps(info, ok, warn, error, multi, rest_cs[1] if len(rest_cs) > 1 else '')
    elif cmd == 'logs':
        rest_cs = (args or '').strip().split(None, 1)
        _logs(info, ok, warn, error, multi, rest_cs[1] if len(rest_cs) > 1 else '')
    elif cmd == 'notify':
        rest_cs = (args or '').strip().split(None, 1)
        _notify(info, ok, warn, error, multi, rest_cs[1] if len(rest_cs) > 1 else '')
    elif cmd == 'perf':
        _perf(info, ok, warn, error, multi)
    elif cmd in ('wifiprobe', 'pcap'):
        _wifiprobe(info, ok, warn, error, multi)
    elif cmd == 'fire':
        rest_cs = (args or '').strip().split(None, 1)
        _fire(info, ok, warn, error, multi, rest_cs[1] if len(rest_cs) > 1 else '')
    elif cmd == 'ble':
        _ble(info, ok, warn, error, multi, rest)
    elif cmd == 'store':
        rest_cs = (args or '').strip().split(None, 1)
        _store(info, ok, warn, error, multi, rest_cs[1] if len(rest_cs) > 1 else '')
    elif cmd == 'web':
        _web(info, ok, warn, error, multi, rest)
    elif cmd == 'style':
        st = ('folders' if rest.startswith('f') else 'menu' if rest.startswith('m')
              else 'gallery' if rest.startswith('g') else None)
        if st is None:
            multi("  Home style: {}".format(_reg('Apps.NovaD1_HomeStyle', 'folders')))
            multi("  novad1 style folders | gallery | menu")
        else:
            try:
                import regedit
                regedit.save('Apps.NovaD1_HomeStyle', st)
                ok("Home style set to '{}'. Re-open the GUI.".format(st), p="NovaD1")
            except Exception as e:
                error("Could not save: {}".format(e))
    elif cmd == 'gui':
        _gui(info, ok, warn, error, multi, bg=('--bg' in rest or 'bg' == rest))
    else:
        warn("Unknown subcommand '{}'. Try: novad1 help".format(cmd))


def _wifiprobe(info, ok, warn, error, multi):
    """Probe whether this firmware can capture 802.11 frames (-> .pcap). The
    make-or-break question for WiFi pcap: stock MicroPython has no promiscuous
    API; real sniffing needs a custom firmware with an esp_wifi C binding. This
    reports exactly what THIS board exposes so we know which path we're on."""
    info("=== Nova D1 — WiFi capture capability probe ===", p="NovaD1")
    import sys
    try:
        import os
        u = os.uname()
        multi("  firmware : {} {}".format(getattr(u, 'sysname', '?'), getattr(u, 'release', '?')))
        multi("  machine  : {}".format(getattr(u, 'machine', '?')))
    except Exception as e:
        multi("  firmware : (uname unavailable: {})".format(e))
    multi("  platform : {}".format(sys.platform))
    found = []
    try:
        import network
        for n in dir(network.WLAN):
            ln = n.lower()
            if 'promisc' in ln or 'monitor' in ln or 'sniff' in ln:
                found.append('WLAN.' + n)
    except Exception as e:
        multi("  network  : (unavailable: {})".format(e))
    have_espnow = False
    try:
        import espnow  # noqa
        have_espnow = True
    except Exception:
        have_espnow = False
    free_kb = 0
    try:
        import gc
        free_kb = gc.mem_free() // 1024
    except Exception:
        pass
    multi("  WLAN sniff API : {}".format(', '.join(found) if found else 'NONE'))
    multi("  espnow (L2)    : {}".format('present' if have_espnow else 'absent'))
    multi("  free RAM       : {} KB  (PSRAM shows as MBs)".format(free_kb))
    multi("")
    if found:
        ok("Capture hook present -> real .pcap is possible! Note these API names.", p="NovaD1")
    else:
        warn("No promiscuous/monitor API in this firmware.", p="NovaD1")
        multi("  Real 802.11 sniffing needs a CUSTOM Nova D1 firmware with an esp_wifi")
        multi("  promiscuous C module (ESP-IDF build). The .pcap WRITER (novapcap) is")
        multi("  already in place for when that lands. Meanwhile a scan-based WiFi")
        multi("  SURVEY (APs / channel / RSSI -> CSV) is the achievable recon now.")


if __name__ == '__main__':
    novad1('scan')
