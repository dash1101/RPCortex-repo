# RPCortex Package Repository

The official package repository for [RPCortex Nebula](https://github.com/dash1101/RPCortex).

---

## Adding the repo to your device

From the RPCortex shell (WiFi required):

```
pkg repo add https://raw.githubusercontent.com/dash1101/RPCortex-repo/main/repo/index.json
pkg update
pkg available
```

Or browse and install packages from your browser — no WiFi, no REPL — at [rpc.novalabs.app/packages.html](https://rpc.novalabs.app/packages.html).

---

## Available packages

| Package | Version | Description |
|---------|---------|-------------|
| HelloWorld | 1.0.0 | Sample demo package for RPCortex |
| Ask | 1.2.0 | Ask an AI a question — Ollama, Groq, Claude, OpenAI |
| SysMon | 1.0.0 | Live system monitor (htop-style) |

---

## Repository structure

```
repo/
  index.json          ← package index (fetched by pkg manager)
  packages/
    helloworld/       ← package source
    helloworld.pkg    ← installable archive
    ask/
    ask.pkg
    sysmon/
    sysmon.pkg
  make_pkg.py         ← build script: source dir → .pkg archive
```

---

## Building a package

A `.pkg` file is a ZIP archive containing your package files and a `package.cfg` descriptor.

**`package.cfg` format:**
```
[Package]
name: MyPackage
version: 1.0.0
description: What it does
author: your-username
entry: mypackage.py
```

**Build:**
```
python repo/make_pkg.py repo/packages/mypackage
```

Full guide: [rpc.novalabs.app/PackageDev.html](https://rpc.novalabs.app/PackageDev.html)

---

## Contributing a package

1. Fork this repo
2. Add your package source under `repo/packages/<name>/`
3. Include a valid `package.cfg`
4. Run `make_pkg.py` to build the `.pkg`
5. Add an entry to `repo/index.json`
6. Open a pull request

---

*RPCortex by [dash1101](https://github.com/dash1101). MIT License.*
