# Nova D1 test suite

Zero-dependency tests for the Nova D1 package logic — they run the **real** package
modules under CPython with the hardware stubbed, so every parser / encoder / file
format is verified without a device or any pip installs.

```sh
python3 run_all.py          # run everything, summarised
python3 test_novacc.py      # or a single file
```

Coverage:

| file | what it locks in |
|------|------------------|
| `test_novanfc.py` | Flipper `.nfc` v4 round-trip (ISO/NTAG/Classic), builders' field order, `identify()` incl. the ATQA byte-order de-risk |
| `test_novacc.py` | `.sub` parse (RAW + decoded Key), `to_flipper`, fire routing, Princeton/CAME/NICE FLO encoders vs the Flipper firmware |
| `test_novable.py` | BLE advertisement packets (Apple proximity, Google Fast Pair) |
| `test_novapcap.py` | libpcap writer — magic/version/records round-trip (Wireshark-openable) |
| `test_nova.py` | scripting: button-grid parse + `do()` action dispatch |
| `test_novamods.py` | PN532 parsers + Classic sector math + NTAG/Classic dump generators (mock PN532) |

`_shims.py` installs the MicroPython/hardware stubs and a tiny assert harness.
Device-only behaviour (real RF/NFC/BLE on-air) is **not** covered here — that's the
on-hardware checklist. This suite guards the logic that *can* be verified off-device.
