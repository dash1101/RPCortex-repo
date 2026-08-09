# RPCortex Package Repository

Every package hosted for RPCortex, in two independent lines. They share nothing
but the word "package": a v1 package is a MicroPython archive, a v2 package is a
compiled relocatable object, and neither device can read the other's index.

| | OS | Index | Packages |
|---|---|---|---|
| **v1 — Vela** | [RPCortex-OS](https://github.com/dash1101/RPCortex-OS), MicroPython | `repo/index.json` | `repo/packages/*.pkg` |
| **v2 — Vela II** | [RPCortex](https://github.com/dash1101/RPCortex), C++ | `repo-v2/index.json` | `repo-v2/packages/*.app` |

---

## v1 — Vela

From the RPCortex shell, with WiFi up:

```
pkg repo add https://raw.githubusercontent.com/dash1101/RPCortex-repo/main/repo/index.json
pkg update
pkg available
```

Or browse and install from a browser — no WiFi, no REPL — at
[rpc.novalabs.app/packages](https://rpc.novalabs.app/packages).

The package management system is documented at
[rpc.novalabs.app/PackageDev](https://rpc.novalabs.app/PackageDev).

## v2 — Vela II

`repo-v2/index.json` is the default repository, compiled into the firmware, so
nothing has to be added:

```
pkg update
pkg search
pkg install <name>
```

`repo-v2/README.md` covers the format, how the index is generated, and what it
takes to add a package.

---
*RPCortex by [dash1101](https://github.com/dash1101). Proprietary, source-available &mdash; &copy; 2026, all rights reserved. See [LICENSE](LICENSE).*
