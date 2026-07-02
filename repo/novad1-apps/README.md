# Nova D1 app store

Downloadable **Nova-UI apps** for the Nova D1 — installed onto the device and shown
on the home, alongside the built-in apps. Lives in `RPCortex-repo` as a separate
folder and uses the **same format as RPCortex packages**: each app is a folder with
a config file (`app.cfg`, the `pkg.cfg` equivalent) plus its files.

```
novad1-apps/
  ble-pranks/
    app.cfg
    ble-pranks.txt
  index.json          # the browse manifest the device fetches
```

## `app.cfg` (mirrors `package.cfg`, with `app.*` keys)

```
app.name: BLE Pranks
app.dev: dash1101
app.ver: 1.0.0
app.category: auto        # auto | Wireless | Sensors | Tools | System
app.kind: buttons         # buttons (a button grid) | py (a Nova-UI Screen, later)
app.entry: ble-pranks.txt
app.desc: Ping nearby phones with fake pairing popups.
```

**Auto-categorise:** with `app.category: auto` the home folder is derived from the
app's content — a button grid's dominant action verb picks it (`ble`/`lora`/`ir`/… →
Wireless, `run` → System, `notify`/`log` → Tools). So an app lands in the right
folder without the author choosing.

### Button-grid apps (`kind: buttons`)
A title plus one action per line — the `ButtonGridScreen` engine the device already
runs:

```
title: BLE Pranks
iPhone AirPods = ble ping apple airpods
Sys Info = run sysinfo
```

Actions: `ir <file> <sig>` · `subghz <file>` · `lora <text>` · `ble ping <apple|android> [model]`
· `ble scan|stop` · `run <shell>` · `notify <text>` · `sleep <s>` · `log <text>`.

## Installing (Nova D1)
- **Now:** drop the app's entry file into the device's scripts store (web *Codes*
  upload, SD, `_xfer`) — it appears in **Scripts** and runs.
- **Planned App Store screen:** browse `index.json` over WiFi → install → it downloads
  to the store, auto-categorises, and pins to the home. See
  `NovaLabs/docs/novad1-spec-app-system.md`.

## Contributing
1. Add `novad1-apps/<name>/app.cfg` + your entry file.
2. Add an entry to `index.json` (`dir`, `name`, `ver`, `category`, `kind`, `desc`).
3. Keep actions self-contained (not dependent on the user's own saved codes).
   The CI test (`repo/tests/novad1/test_appstore.py`) validates every app's cfg,
   entry file, and (for button grids) that all actions use a known verb.
