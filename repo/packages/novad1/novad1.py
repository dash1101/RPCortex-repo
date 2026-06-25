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

_DEF_I2C = {'sda': 8, 'scl': 9}
# 3 buttons total (encoder SW + 2). btn2=16 keeps GPIO15 free for the SD CS.
_DEF_PINS = {'enc_a': 4, 'enc_b': 5, 'enc_sw': 6, 'btn1': 7, 'btn2': 16}

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


def _reg(key, default=None):
    try:
        import regedit
        v = regedit.read(key)
        return v if v else default
    except Exception:
        return default


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
    sda = int(_reg('Apps.NovaD1_SDA', _DEF_I2C['sda']))
    scl = int(_reg('Apps.NovaD1_SCL', _DEF_I2C['scl']))
    return sda, scl


def _input_pins():
    pins = dict(_DEF_PINS)
    for k in pins:
        v = _reg('Apps.NovaD1_PIN_' + k)
        if v:
            try:
                pins[k] = int(v)
            except ValueError:
                pass
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
    return {'wifi': wifi, 'time': tstr, 'power': pwr, 'notify': nt}


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
    multi("")
    multi("  Reboot to start. The UI runs in the background; the shell stays free.")
    multi("  Undo with: autonomy off   (and: service remove novad1 gui --bg)")


def _status(info, ok, warn, error, multi):
    info("=== Nova D1 — status ===", p="NovaD1")
    multi("  Headless boot: {}".format(_reg('Settings.Autonomous', 'off')))
    sda, scl = _i2c_pins()
    multi("  I2C: SDA={} SCL={}   Display: {}".format(sda, scl, _reg('Apps.NovaD1_Display', 'sh1106')))
    p = _input_pins()
    multi("  Encoder A/B/SW: {}/{}/{}   Buttons: {}/{}".format(
        p['enc_a'], p['enc_b'], p['enc_sw'], p['btn1'], p['btn2']))
    mods = _detect_modules()
    present = [k for k in mods if mods[k]]
    multi("  Detected: {}".format(', '.join(present) if present else 'none detected'))
    home = _reg('Apps.NovaD1_Home')
    multi("  Home apps: {}".format(home if home else 'all (default)'))
    multi("  Plan: NovaLabs/docs/novad1-dev-plan.md")


def _apps(info, ok, warn, error, multi, rest=''):
    """Homepage config: choose which apps show on the shelf (Apps.NovaD1_Home)."""
    import novagui
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
    info("=== Nova D1 — home apps ===", p="NovaD1")
    for k, l in allapps:
        on = (enabled is None) or (k in enabled)
        multi("  [{}] {:10} {}".format('x' if on else ' ', k, l))
    multi("")
    multi("  novad1 apps show <key> | hide <key> | reset")


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


def _boot_or_recover(ui, novagui):
    """Set up the initial screen stack: recovered-error flash, or the once-per-boot
    splash + system check, or just home."""
    global _booted
    last = _reg('Apps.NovaD1_LastError')
    if last:
        _clear_err()
        ui.stack.append(novagui.ErrorScreen(last))
    elif not _booted:
        _booted = True
        try:
            import novasound
            novasound.chime()          # boot chime (gated + try-excepted inside)
        except Exception:
            pass
        ui.stack = novagui.make_boot_stack(ui.stack[0])
        if _reg('Apps.NovaD1_PIN'):            # gate the UI behind the PIN if set
            ui.stack.insert(1, novagui.PinScreen('verify'))
        _nlog('Nova D1 GUI started')


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
        if first and _reg('Apps.NovaD1_Web', 'off') == 'on':
            set_web(True)                     # auto-host the control panel
        if first:
            first = False
            try:
                import novartc
                novartc.boot_sync()           # DS3231 -> RTC if present (offline time)
            except Exception:
                pass
            if not _booted and not _reg('Apps.NovaD1_LastError'):
                # Screen ON immediately — paint the splash before any settle/boot
                # work so the user sees it ASAP (hides the Nova-side boot time; the
                # OS POST happens before this service starts, OLED dark then).
                try:
                    import novasplash
                    novasplash.draw(ui.canvas, 0.5)
                    ui.display.show(ui.canvas)
                except Exception:
                    pass
                # Optional extra settle hold (default 0 — the animated splash already
                # gives ~1.5s of light loop activity before any heavy probe).
                try:
                    d = int(_reg('Apps.NovaD1_Boot_Delay', 0))
                except (TypeError, ValueError):
                    d = 0
                if d > 0:
                    try:
                        await asyncio.sleep_ms(d)
                    except Exception:
                        pass
        _boot_or_recover(ui, novagui)
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
        multi("  novad1 scan        Probe the I2C bus for Nova D1 modules")
        multi("  novad1 setup       Headless boot + register the GUI as a service")
        multi("  novad1 status      Show what's configured")
        multi("  novad1 apps ...    Choose which apps show on the home")
        multi("  novad1 style g|m   Home layout: gallery (icons) or menu (list)")
        multi("  novad1 logs [n]    Show the Nova event log (or 'clear')")
        multi("  novad1 notify <t>  Push a notification to the Nova UI")
        multi("  novad1 web on|off  Phone control panel over WiFi")
        multi("  novad1 gui [--bg]  Launch the Nova GUI (--bg = background service)")
        multi("")
        multi("  Tips: LED is WS2812 on GPIO48 by default — reg set")
        multi("  Apps.NovaD1_PIN_led <pin> / Apps.NovaD1_LED_Mode gpio if needed.")
        return
    if cmd == 'scan':
        _scan(info, ok, warn, error, multi)
    elif cmd == 'setup':
        _setup(info, ok, warn, error, multi)
    elif cmd == 'status':
        _status(info, ok, warn, error, multi)
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
    elif cmd == 'web':
        _web(info, ok, warn, error, multi, rest)
    elif cmd == 'style':
        st = 'menu' if rest.startswith('m') else ('gallery' if rest.startswith('g') else None)
        if st is None:
            multi("  Home style: {}".format(_reg('Apps.NovaD1_HomeStyle', 'gallery')))
            multi("  novad1 style gallery | menu")
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


if __name__ == '__main__':
    novad1('scan')
