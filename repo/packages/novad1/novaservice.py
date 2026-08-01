# Desc: Nova D1 GUI service — the background runner, split out of novad1.
# File: /Packages/NovaD1/novaservice.py
#
# This exists purely so the autostarted GUI does not drag the shell CLI into RAM.
# The service used to live in novad1.py, which is the `d1 ...` command module and
# ~44 KB of bytecode: pins editor, app store, code fire commands, self-updater.
# Starting the GUI meant loading every byte of it, and the GUI is what runs on
# every boot while the CLI is what you use occasionally, so the whole CLI was
# resident permanently on a board with barely any headroom.
#
# Registered as its own shell command (`novagui`), so services.cfg can autostart
# the GUI without novad1 ever being imported. `d1 gui` still works — novad1
# imports from here.
#
# MicroPython-safe: no f-strings, positional split, .format() only.

import sys

from novacore import reg as _reg
import novaboard


_booted = False


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

_I2C_KNOWN = {
    0x3c: ('display', 'OLED (SH1106/SSD1306)'),
    0x3d: ('display', 'OLED (alt address)'),
    0x68: ('rtc', 'DS3231 RTC'),
    0x24: ('nfc', 'PN532 NFC/RFID'),
    0x48: ('nfc', 'PN532 NFC/RFID (alt)'),
}

_INPUT_NAMES = ('enc_a', 'enc_b', 'enc_sw', 'btn1', 'btn2')


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
              "category: Testing\n"
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
        # Background services are imported only if they are actually going to
        # RUN. Importing them to ask whether they should run costs the same RAM
        # as running them: novamsg pulls in the LoRa stack and novawatch the BLE
        # scanner, together ~12 KB, on a device where the package already uses
        # most of the heap. Both are checked from config first.
        # LoRa messaging is opt-in for the same reason. A board profile defines
        # sx_cs whether or not an SX1276 is actually soldered on, so the pin says
        # nothing about whether the radio exists — and importing novamsg to ask
        # costs the whole LoRa stack. Most devices do not have the module fitted.
        try:
            if str(_reg('Apps.NovaD1_LoRa', 'off')).lower() in ('on', 'true', '1'):
                import novamsg
                if not novamsg._started:
                    asyncio.create_task(novamsg.manager())
        except Exception:
            pass
        try:                                  # radio observer — opt-in, off by default
            if str(_reg('Apps.NovaD1_Watch', 'off')).lower() in ('on', 'true', '1'):
                import novawatch
                if not novawatch.started():
                    asyncio.create_task(novawatch.observer())
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
                # The FIRST frame, not a middle one. Painting t=0.5 here put a
                # half-finished "Nova" on screen, and then SplashScreen started
                # its animation from t=0 — so it looked like the boot began,
                # stalled, and began again. t=0 is where the animation starts, so
                # the handover is invisible.
                import novasplash
                novasplash.draw(ui.canvas, 0.0)
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


_SVC_NAME = 'novad1'


def novagui(args=None):
    """`novagui [--bg|stop|status]` — run or manage the Nova D1 GUI.

    The autostart entry point. services.cfg holds `novagui --bg`, so booting the
    GUI imports this module and novagui.py and nothing else; novad1.py, the
    ~44 KB command module, stays out of RAM until you actually type `d1`.

    The first parameter must be `args` (None for a bare command) — the shell
    calls a command entry as func(args)."""
    import RPCortex as _R
    a = (args or '').strip().lower()
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')

    if a in ('stop',):
        if lp is not None and hasattr(lp, 'unregister_service'):
            lp.unregister_service(_SVC_NAME)
            _R.ok('Nova GUI service stopped.', p='NovaD1')
        else:
            _R.error('Service engine unavailable.')
        return
    if a in ('status',):
        run = (lp is not None and hasattr(lp, 'service_running')
               and lp.service_running(_SVC_NAME))
        _R.multi('  Nova GUI service: {}'.format('running' if run else 'stopped'))
        return
    if a in ('--bg', 'bg', '-b'):
        if lp is None or not hasattr(lp, 'register_service'):
            _R.error("Service engine unavailable — the async shell isn't active.")
            return
        if hasattr(lp, 'service_running') and lp.service_running(_SVC_NAME):
            _R.multi('  Nova GUI service already running.')
            return
        lp.register_service(_SVC_NAME, _gui_service)
        _R.ok('Nova GUI service started.', p='NovaD1')
        return

    # Foreground: run the UI on this terminal until it exits.
    _R.info('Starting the Nova D1 UI (Ctrl+C to stop)...')
    ui, err = _build_ui()
    if err:
        _R.error(err)
        return
    try:
        ui.run()
    except KeyboardInterrupt:
        _R.info('Nova D1 UI stopped.')
