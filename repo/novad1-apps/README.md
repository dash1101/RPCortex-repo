# Nova D1 app store

Downloadable **Nova-UI apps** for the Nova D1 — installed onto the device and shown
on the home, alongside the built-in apps. Lives here (in `RPCortex-repo`) as a
separate folder, mirroring how the package repo (`repo/packages/`) works.

## App format (v1: button-grid script-apps)

The first, simplest app kind is a **button grid** — a `.txt` file the Nova D1 already
knows how to run (the `ButtonGridScreen` engine). It's a title plus one action per
line:

```
title: BLE Pranks
# comment lines start with #
iPhone AirPods = ble ping apple airpods
Android = ble ping android headphones
Sys Info = run sysinfo
```

Actions (the `nova.do()` dispatcher):
`ir <file> <signal>` · `subghz <file>` · `lora <text>` · `ble ping <apple|android> [model]`
· `ble scan|stop` · `run <shell cmd>` · `notify <text>` · `sleep <s>` · `log <text>`.

A future `kind: py` will allow full Nova-UI `Screen` apps (a manifest + module).

## The index

`index.json` is the manifest the device fetches:

```json
{ "repo": "...", "version": 1,
  "apps": [ {"name","file","category","kind","author","desc"} ] }
```

`category` is one of the home folders (Wireless / Sensors / Tools / System).

## Installing (on the Nova D1)

- **Now:** drop an app `.txt` into the device's scripts store (web panel *Codes*
  upload, SD, or `_xfer`) — it appears in the **Scripts** app and runs.
- **Planned (App Store screen):** browse this `index.json` over WiFi → pick an app →
  it downloads to the store and (optionally) pins to the home. See
  `NovaLabs/docs/novad1-spec-app-system.md`.

## Contributing an app

1. Add your `apps/<name>.txt` (button grid).
2. Add an entry to `index.json`.
3. Keep it self-contained (actions that don't depend on the user's own saved codes
   are best for a shared app). The CI test (`repo/tests/novad1/test_appstore.py`)
   checks every listed app parses as a valid button grid.
