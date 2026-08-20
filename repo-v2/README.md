# RPCortex v2 package repository

Packages for the C++ RPCortex ([RPCortex](https://github.com/dash1101/RPCortex)).
Separate from `repo/`, which serves the MicroPython line and keeps working
unchanged — the two formats have nothing in common beyond the word "package".

## What a v2 package is

One file: a relocatable ELF object with a `.app` extension. The OS loads it at
runtime, relocates it into RAM, resolves its calls against the firmware symbol
table, and runs it. It registers shell commands, which go live immediately and
are swept when it unloads.

There is no archive, no directory layout and no `package.cfg`. The name, the
version and the ABI it was built against travel inside the binary, in an
`RpcAppHeader`, so there is no second place for them to disagree.

## Architecture

Packages are built for **ARMv6-M** (`-mcpu=cortex-m0plus`) and one binary runs on
every supported board. ARMv6-M is a strict subset of ARMv8-M Mainline, so an M0+
binary executes on an RP2350's M33 — the reverse is not true.

The alternative was a package per architecture, which means two builds per
release, two things to get wrong at install time, and a wrong-architecture
package that hard-faults rather than failing cleanly. `make_index.py` refuses
anything that is not ARMv6-M for exactly that reason, and refuses an unreadable
architecture too: failing closed is the only safe default when the cost of being
wrong is a fault on someone's device.

The `arch` field in the index is a separate question from what the binary
contains: it is which boards the package is **offered** to. It defaults to
`armv6m` — a portable binary runs on every board — and a package narrows it in
`meta.json` when it should not be offered everywhere. Nova D1 is the case that
needs it: its binary is ARMv6-M like the rest, but it is position-independent and
loads from a flash slot only the RP2350 has, so it is published as `armv8m` and
the index keeps it off the RP2040 boards it could never run on. "Is this binary
ARMv6-M" and "who do we offer it to" are read from two different places — the
binary and `meta.json` — because they are two different facts.

## Layout

```
index.json      generated — the package list devices fetch
meta.json       hand-written — descriptions and authors, keyed by package name
packages/       the .app files
make_index.py   rebuilds index.json from packages/
```

## Adding a package

1. Build it against `os/include/rpc_app.h` with the app flags in the OS
   `CMakeLists.txt` (or add it there via `rpc_add_app`).
2. Copy the `.app` into `packages/`.
3. Add its description to `meta.json` — and, for a package that only runs on the
   RP2350 (position-independent, loaded from a flash slot), an `"arch": "armv8m"`
   there too, so it is not offered to the RP2040 boards.
4. Run `./make_index.py`.
5. Commit both the `.app` and the regenerated `index.json`.

`./make_index.py --check` verifies the index matches the packages without
writing anything, and exits non-zero if it does not — suitable for CI.

## Index format

```json
{
  "name": "RPCortex Package Repository",
  "format": 2,
  "maintainer": "dash1101",
  "packages": [
    {
      "name":   "greet",
      "ver":    "1.0",
      "desc":   "…",
      "author": "dash1101",
      "abi":    "1.2",
      "arch":   "armv6m",
      "size":   1732,
      "sha256": "…",
      "url":    "https://raw.githubusercontent.com/…/greet.app"
    }
  ]
}
```

`format: 2` distinguishes this from the v1 index at `repo/index.json`, so a
client that fetches the wrong one can say so rather than misparse it.

`abi` is the API major.minor the package was built against. The OS refuses a
package whose major differs from its own, and refuses a newer minor — that one
may want a symbol the running firmware does not export. `sha256` is over the
whole file, so a truncated download is caught before anything is installed.
