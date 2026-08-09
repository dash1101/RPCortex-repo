# Nova D1 test suite

Zero-dependency tests for the Nova D1 package logic — they run the **real** package
modules under CPython with the hardware stubbed, so every parser / encoder / file
format is verified without a device or any pip installs.

```sh
python3 run_all.py          # run everything, summarised
python3 test_novacc.py      # or a single file
```

`run_all.py` discovers every `test_*.py` beside it and prints the file count on
the last line, so the list below describes areas rather than naming files that
come and go.

| Area | What it locks in |
|------|------------------|
| File formats | Flipper `.nfc` v4, `.sub`, `.ir` and `.rfid` round-trips, the builders' field order, and `identify()` including the ATQA byte-order de-risk |
| Encoders | Princeton, CAME and NICE FLO against the Flipper firmware, and the NEC, Sony, RC5 and RC6 carrier and header timings |
| Radios | BLE advertisement packets (Apple proximity, Google Fast Pair), the libpcap writer, which has to open in Wireshark, and that firing a code with the radio absent fails fast instead of quietly |
| Board and pins | Profile resolution, the RP2 fixed peripheral groups and board-reserved GPIO, and the generated wiring doc — which fails the suite when it has gone stale, and skips when the repo holding it is not checked out |
| UI and runner | Screen fitting, icons, fonts, the home and app catalogue, navigation, and the button-grid `do()` dispatch |
| Everything else | Power, clock, notifications, updates, the app store, the shell app, and the module split |

`_shims.py` installs the MicroPython/hardware stubs and a tiny assert harness.
Device-only behaviour (real RF/NFC/BLE on-air) is **not** covered here — that's the
on-hardware checklist. This suite guards the logic that *can* be verified off-device.
