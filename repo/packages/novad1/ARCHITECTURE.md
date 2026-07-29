# Nova D1 — Architecture

Nova D1 is **not firmware**. It is a suite of MicroPython modules that run *on top of*
RPCortex Vela (the OS) and turn a headless ESP32-S3 + OLED + encoder into a Flipper-style
cyber multi-tool. Everything here lives in `/Packages/NovaD1/` on the device and is
driven by the `novad1` shell command + a cooperative GUI service.

This document describes the layers, the one dependency rule, and — honestly — where the
code does not yet obey it. It is written from the **actual import graph**, not an
aspiration; if you change the imports, update this file.

## The layers

Modules are grouped into layers. **The rule: a module may import only from its own layer
or a layer below it.** Lower = closer to the metal / more generic. `novacore` is the leaf.

```
  L5  Orchestration   novad1 · nova
  L4  UI              novagui · novaicons · novasplash
  L3  Services/data   novastore · novaappstore · novaweb · novamsg · novalog · novanotify
  L2  Codec/format    novanfc · novarfid · novapcap · novaappcfg · novacrypt   (pure logic)
  L1  HAL/drivers     novamods · novainput · novacanvas · novafont · novartc ·
                      novapower · novasound · novalora · novamesh · novable · novawifi
  L0  Core (leaves)   novacore · novaboard          (novacore imports only regedit;
                                                     novaboard imports only novacore)
```

### L0 — Core
`novacore` holds the cross-cutting helpers every module needs: `reg()` / `save_reg()`
(registry access). It imports **only** `regedit`, lazily, so it can never be part of a
cycle. ~12 modules used to each re-declare their own `_reg`; they now
`from novacore import reg as _reg`. This is the one hard invariant: **keep novacore a leaf.**

`novaboard` is the other L0 leaf: **one source of truth for pins and buses.** It holds
board profiles (`esp32s3` shipping, `rp2350` draft) and resolves a pin as
*registry override → board profile → caller's fallback*, so the registry always wins and
an already-configured device is never silently re-pinned. Six drivers used to carry their
own `_pin()` with their own hardcoded ESP32-S3 defaults (`novamods`, `novair`, `novalora`,
`novacc`, `novasound`, `novapower`); each is now a thin delegate to `novaboard.pin()`.
Adding a board is a data change — the drivers don't move. It also carries `check()`, which
validates a profile against the RP2 fixed peripheral pin groups and board-reserved GPIO,
so an unassignable pinmap is caught on the host rather than on the bench.

Two invariants live here. **`novaboard.OPT_IN`** (`battery`, `vbus`) must never get a
profile default: `novapower` reads those pins only when configured, so a default would
turn off the guard that stops an unwired floating ADC reporting a fake battery level. And
`pin()` accepts either a short name or a full `Apps.NovaD1_PIN_*` key, because the drivers
grew both conventions and neither call site had to change.

### L1 — HAL / drivers
Everything that talks to hardware: `machine` (SPI/I2C/PWM/ADC/Pin), `bluetooth`,
`network`, `framebuf`. The rest of the suite goes through these so a port to different
hardware touches only this layer. The test suite stubs `machine`/`network` and imports
these with the hardware faked.

### L2 — Codec / format (pure logic)
Parsers, encoders, and file-format writers with **no hardware imports at all**:
`.nfc`/`.rfid`/`.sub`/`.ir` (de)serialization, the pcap writer, `app.cfg` parsing,
crypto. This layer is *why the CPython test suite exists* — it runs these with zero
hardware and zero MicroPython, so the format logic is verified on every commit
(`repo/tests/novad1/`). Keep new format/protocol logic here and hardware-free.

### L3 — Services / data
Stateful services: `novastore` (persist codes/config to flash or SD), `novaappstore`
(fetch + install apps over HTTPS), `novaweb` (the phone control panel), `novamsg` (the
LoRa messaging queue), `novalog`, `novanotify`.

### L4 — UI
`novagui` builds the screens + the `NovaUI` event loop; `novaicons`/`novasplash` are
assets. The UI reads services + drivers; nothing below should import the UI.

### L5 — Orchestration
`novad1` is the entry point (the `novad1` command, hardware wiring, service registration,
the GUI service factory). `nova` parses button-grid "apps" and dispatches their actions.

## Honest known-debt (verified upward edges)

These are real violations of the down-only rule. They are documented, not hidden — each
is a pragmatic trade-off, and each is a candidate for a later, careful fix.

1. **Shared-SPI arbitration is an upward call.** `novacc` (L1/L2), `novamods` (L1), and
   `novastore` (L3) each call `novamsg.pause()` / `resume()` (L3) to yield the shared SPI
   bus before their own SPI access, so the CC1101 / SD / module-scan don't collide with
   the LoRa radio. `novamsg` owns the radio that holds the bus, so arbitration lives
   there. *Candidate:* a bus-yield hook that doesn't couple lower layers to a service —
   but not via `novacore` (that would break the leaf rule). Left as debt.

2. **`novagui` ↔ `novad1` lazy cycle.** The UI reaches up to orchestration in two spots:
   `novad1.set_web()` (toggle the web service) and `novad1._nova_base()` (data path). Both
   are lazy imports inside functions, so MicroPython resolves the cycle at call time.
   *Candidate:* move the `_nova_base()` path helper down to `novacore`.

3. **Split codec+driver modules.** `novacc` and `novair` each bundle a *pure* codec
   (`encode`/`parse_flipper`, tested hardware-free) with a hardware driver (SPI/PWM) in
   one file — so they appear in both L1 and L2. A clean split would separate
   `novaXX_codec` from `novaXX_hw`; deferred (not worth the churn vs. the risk today).

4. **`novagui.py` — the monolith split (in progress).** It began as a ~2,900-line file
   (~50 Screen classes) — the biggest structural smell in the suite. The shape being
   pulled out is **flat sibling modules** — `novaui.py` (the leaf: Screen base + layout
   tokens + draw helpers + the input `ev` re-export) plus `novagui_<category>.py` files
   that import only the leaf; `novagui.py` keeps the orchestration (`build_home` /
   `_all_apps` / the NovaUI runner / home config). **Flat, not a `novagui/` package** —
   the browser sim and the on-device loader both resolve modules by flat filename, so a
   package would break both. Split incrementally, one category per commit (suite + sim
   MODS manifest each time), never in one move.
   - **Done:** `novaui.py` (the leaf), `novagui_sensors.py` (LED/Battery/Environment/
     Clock), `novagui_radios.py` (Messages/GPS/NFC/IR/Sub-GHz/BLE/LoRa/ButtonGrid —
     11 classes), `novagui_system.py` (WiFi/Set Time/System Check/Notifications/PIN).
     `novagui.py` is down to ~1,700 lines.
   - **Deliberately still in `novagui.py`:** the settings/management screens that reach
     the NovaUI runner — **Display, ManageApps, Settings, AppStore, Command** — plus the
     runner chrome (IconGallery, boot/splash/error screens, ModuleTestScreen). They use
     `_disp()` / `_mark_home_dirty()` / `_apply_*` / the category machinery, which live
     with the runner. Extracting them cleanly needs the **category subsystem**
     (`_app_category` / `_CAT_OVERRIDE` / `_set_cat_override` / `_load/_save_cat_overrides`)
     pulled into its own leaf module first — the next deliberate step, done verify-first,
     not with reach-around `import novagui` calls.

5. **`nova.py` spans two layers** — it both parses button-grid apps (codec) and dispatches
   their actions into the radios (orchestration).

## Conventions

- **MicroPython-safe:** no f-strings, `str.split(None, n)` positional, `.format()` only.
- **Header:** every module opens with `# Desc:` / `# File:` and a one-paragraph purpose.
- **Config:** read/write the registry only through `novacore.reg` / `save_reg`
  (`Apps.NovaD1_*` keys). Don't re-roll `_reg`.
- **Tests:** standalone scripts in `repo/tests/novad1/` (no pytest); `python3 run_all.py`
  runs all. Add format/protocol tests at L2 — they need no hardware. Hardware paths are
  exercised with `machine` stubbed via `_shims.py`.

## Adding a module

Put it in the lowest layer that fits, give it the standard header, and depend only
downward. If it needs the registry, import from `novacore`. If it's a parser/encoder,
keep it hardware-free and add a test. If it needs a new home-screen app, wire it in
`novagui._all_apps()` and give it an `_APP_CAT` category.
