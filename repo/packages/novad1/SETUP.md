# Nova D1 — setup

Getting a Nova D1 from "boards on the desk" to "UI on the screen". Everything here
is a shell command on the device — you never need to edit the registry by hand.

`d1` and `novad1` are the same command; `d1` is used below.

---

## 1. Install

Nova D1 is an RPCortex package. From the device shell:

```
pkg update
pkg install NovaD1
```

## 2. Tell it what hardware you have

Two things decide whether anything appears on screen: the **board** (which pins are
which) and the **panel** (which OLED controller).

```
d1 pins board            # list profiles, '*' is active, and which one was detected
d1 display               # list panels, '*' is active
```

Nova D1 identifies the board from `os.uname()` and uses that when nothing is
configured, so most of the time this is already right. Three boards are supported:

| Profile | Board |
|---|---|
| `esp32s3` | ESP32-S3 devkit (N16R8) — the shipping build |
| `pico2w` | Raspberry Pi Pico 2 W |
| `picoplus2w` | Pimoroni Pico Plus 2 W |

To set it yourself:

```
d1 pins board auto       # trust the detected board
d1 pins board pico2w     # or name it
d1 display ssd1309       # 2.42" panel  (sh1106 is the default)
```

Anything you set by hand always wins over detection, so a hand-wired board is never
silently re-pinned by an update.

## 3. Check the wiring

```
d1 pins
```

Every pin, the GPIO it resolves to, **where that value came from**, and what it's for:

```
  NAME       GPIO  SOURCE    WHAT
  ir_tx        39  board     IR LED
  sda           8  board     I2C data (OLED, RTC, PN532)
  battery       -  unset     battery ADC (leave unset if unwired)
```

- `board` — from the board profile, i.e. the default for this hardware.
- `override` — you set it. Survives updates.
- `unset` — no value. Optional pins stay unset until you wire them.

Wired something differently? Set just that pin:

```
d1 pins set ir_tx 12
d1 pins clear ir_tx      # back to the board default
```

Then confirm the map is physically possible:

```
d1 pins check
```

This catches two GPIO driving one pin, and — on RP2350 — SPI/I2C pins that aren't
legal for those peripherals. RP2 ties SPI and I2C to fixed GPIO groups, so a
reasonable-looking pinmap can simply be unassignable. Better to hear it here than
after wiring.

## 4. Find your modules

```
d1 scan
```

I2C probe. The OLED (0x3C or 0x3D), RTC (0x68) and PN532 (0x24/0x48) answer here.
Nothing at all usually means SDA/SCL are wrong or swapped — check step 3.

SPI modules (CC1101, SX1276, SD) don't show up on an I2C scan. Test those from the
UI: **System Check**, or Settings → module tests.

## 5. Turn it on

```
d1 setup
```

This enables headless boot (the device boots straight into the Nova UI as your user)
and registers the GUI as a background service, so the serial shell stays usable. It
finishes by printing the board, panel, I2C pins and what answered on the bus — read
that before rebooting, since it's where a wrong board or panel shows up.

Then reboot.

To run the UI without committing to headless boot:

```
d1 gui                   # foreground, Ctrl+C to exit
d1 gui --bg              # background service, shell stays free
```

## 6. Check in on it

```
d1 status                # board, pins, overrides, what was detected
d1 logs                  # the Nova event log
d1 perf                  # frame timing
```

---

## Optional bits

**Battery gauge.** Off until you wire it, deliberately — an unconnected ADC floats
and would report a confident, wrong battery level.

```
d1 pins set battery 1    # an ADC-capable pin
reg set Apps.NovaD1_BattDiv 2.0    # your divider ratio
```

**USB-power detect.** `d1 pins set vbus <pin>`.

**Phone control panel** over WiFi:

```
d1 web on
```

**Undo headless boot:**

```
autonomy off
service remove novad1 gui --bg
```

---

## Troubleshooting

**Blank screen.** In order: is the panel the right one (`d1 display`)? Does the OLED
answer on I2C (`d1 scan`)? Are SDA/SCL right (`d1 pins`)? The SH1106 and SSD1306/09
share an I2C address and can't be told apart in software, so if the panel is wired
correctly and still blank, the controller setting is the usual culprit.

**Garbled or shifted image.** Wrong panel type. The SH1106 is a 132-column part
showing 128, so it needs a 2-pixel offset the others don't — pick the wrong one and
the image shifts or tears.

**UI comes up, a module doesn't.** Run its test in System Check. If it fails, check
that module's pins in `d1 pins`, and its power — the 3V3 rail has a current limit and
several radios transmitting at once can brown out.

**Nothing on I2C after changing pins.** Restart the GUI (`d1 gui`) or reboot — the
bus is opened once at start.

**Everything was fine, then an update.** Overrides live in the registry and survive
updates, board profiles ship with the package. `d1 pins` shows which is which, so
compare the `override` rows against how the device is actually wired.

---

## Where things live

| What | Where |
|---|---|
| Board profiles, pin resolution | `novaboard.py` |
| Display backends | `display.py` |
| Wiring reference (ESP32-S3) | `docs/novad1-wiring.md`, in the NovaLabs repository |
| Module layering + invariants | `ARCHITECTURE.md` |
| UI design notes | `DESIGN.md` |
