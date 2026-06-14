# Desc: mkpkg - build RPCortex packages on the device - Pulsar OS
# File: /Packages/MkPkg/mkpkg.py
# Version: 0.1.0
# Author: dash1101
#
# An on-device package workshop: scaffold a new package, validate it, and pack
# a folder into an installable .pkg — no PC toolchain needed. (Packs SOURCE
# .py; there's no mpy-cross on the device, but source packages install + run
# fine. Use the IDE's 't' to live-test, then mkpkg pack + pkg install.)
#
# Shell command:  mkpkg  (also: pkgbuild)
#
#   mkpkg new <Name> [cmd]   scaffold ./<name>/ (package.cfg + <name>.py)
#   mkpkg check [dir]        validate a package folder (cfg fields, module, fn)
#   mkpkg pack [dir] [out]   zip a package folder into <name>.pkg (ZIP_STORED)
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys
import uos

from RPCortex import ok, info, warn, error, multi

_DIR_FLAG = 0x4000


# -- helpers ---------------------------------------------------------------

def _is_dir(p):
    try:
        return (uos.stat(p)[0] & _DIR_FLAG) != 0
    except OSError:
        return False


def _exists(p):
    try:
        uos.stat(p)
        return True
    except OSError:
        return False


def _cwd():
    try:
        return uos.getcwd().rstrip('/')
    except Exception:
        return ''


def _abs(p):
    return p if p.startswith('/') else (_cwd() + '/' + p)


def _read_cfg(path):
    cfg = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('pkg.') and ':' in line:
                    k, v = line.split(':', 1)
                    cfg[k.strip()] = v.strip()
    except OSError:
        pass
    return cfg


# -- new: scaffold ---------------------------------------------------------

def _new(name, cmd):
    if not name:
        warn("Usage: mkpkg new <Name> [command]")
        return
    mod = name.lower()
    cmd = (cmd or mod).lower()
    d = _abs(mod)
    if _exists(d):
        error("'{}' already exists.".format(d))
        return
    try:
        uos.mkdir(d)
    except OSError as e:
        error("Could not create '{}': {}".format(d, e))
        return

    try:
        owner = ''
        try:
            import regedit
            owner = regedit.read('System.Owner') or regedit.read('Settings.Active_User') or 'you'
        except Exception:
            owner = 'you'
        cfg = ("pkg.name: {}\n"
               "pkg.dev: {}\n"
               "pkg.ver: 0.1.0\n"
               "pkg.dir: /Packages/{}\n"
               "pkg.desc: {} - a new RPCortex package\n"
               "pkg.cmd: {}:/Packages/{}/{}.py:{}\n").format(
                   name, owner, name, name, cmd, name, mod, cmd)
        with open(d + '/package.cfg', 'w') as f:
            f.write(cfg)

        src = ("# {} package for RPCortex\n"
               "from RPCortex import ok, info, warn, multi\n\n\n"
               "def {}(args=None):\n"
               "    info(\"{} v0.1.0\")\n"
               "    if args:\n"
               "        multi(\"  you said: \" + args)\n"
               "    else:\n"
               "        multi(\"  Hello from {}!  (edit /Packages/{}/{}.py)\")\n").format(
                   name, cmd, name, name, name, mod)
        with open(d + '/' + mod + '.py', 'w') as f:
            f.write(src)
    except OSError as e:
        error("Write failed: {}".format(e))
        return

    ok("Scaffolded package '{}' in {}/".format(name, d))
    multi("  Edit:   {}/{}.py".format(d, mod))
    multi("  Test:   ide  ->  open {}  ->  press 't'   (live, no install)".format(d))
    multi("  Build:  mkpkg pack {}     then:  pkg install {}.pkg".format(mod, mod))


# -- check: validate -------------------------------------------------------

def _check(d):
    d = _abs(d or '.')
    if d.endswith('/.'):
        d = d[:-2] or '/'
    cfgp = d + '/package.cfg'
    if not _exists(cfgp):
        error("No package.cfg in '{}'.".format(d))
        return False
    cfg = _read_cfg(cfgp)
    ok_all = True

    def need(k):
        if not cfg.get(k):
            error("  missing {}".format(k)); return False
        ok("  {} = {}".format(k, cfg[k])); return True

    info("Checking package in {}".format(d))
    for k in ('pkg.name', 'pkg.ver', 'pkg.dir'):
        ok_all = need(k) and ok_all

    cmd = cfg.get('pkg.cmd', '')
    if not cmd:
        warn("  no pkg.cmd (file-only package — fine if intentional)")
    else:
        for entry in cmd.split(';'):
            parts = entry.split(':')
            if len(parts) < 3:
                error("  bad pkg.cmd entry: {}".format(entry)); ok_all = False; continue
            name, path, func = parts[0], parts[1], parts[2]
            base = path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
            # the module source must be in this folder
            srcs = [d + '/' + base + '.py', d + '/' + base + '.mpy']
            present = [s for s in srcs if _exists(s)]
            if not present:
                error("  '{}': module '{}' not found here".format(name, base)); ok_all = False
                continue
            # if .py source present, confirm the function is defined
            pys = d + '/' + base + '.py'
            if _exists(pys):
                found = False
                try:
                    with open(pys) as f:
                        for line in f:
                            if line.startswith('def ' + func + '(') or line.startswith('def ' + func + ' '):
                                found = True; break
                except OSError:
                    pass
                if found:
                    ok("  cmd '{}' -> {}.{}()".format(name, base, func))
                else:
                    error("  cmd '{}': function '{}' not defined in {}.py".format(name, func, base))
                    ok_all = False
            else:
                ok("  cmd '{}' -> {} (compiled)".format(name, base))
            # builtin-name collision warning
            if base in ('dht', 'time', 'socket', 'json', 'os', 'gc', 'math',
                        'network', 'machine', 'sys', 're', 'struct'):
                warn("  module name '{}' collides with a MicroPython builtin — rename it".format(base))

    if ok_all:
        ok("Package looks valid.")
    else:
        error("Package has problems (see above).")
    return ok_all


# -- pack: build a .pkg (ZIP_STORED) ---------------------------------------

def _zip_stored(out_path, entries):
    """Write a ZIP with STORED (uncompressed) entries — the .pkg format.
    entries: list of (arcname, bytes)."""
    import struct
    crc = None
    try:
        from binascii import crc32 as crc
    except Exception:
        try:
            from uzlib import crc32 as crc
        except Exception:
            crc = None
    cd = []
    offset = 0
    with open(out_path, 'wb') as f:
        for name, data in entries:
            nb = name.encode('utf-8')
            c = (crc(data) & 0xffffffff) if crc else 0
            sz = len(data)
            lfh = struct.pack('<IHHHHHIIIHH', 0x04034b50, 20, 0, 0, 0, 0, c, sz, sz, len(nb), 0)
            f.write(lfh); f.write(nb); f.write(data)
            cd.append(struct.pack('<IHHHHHHIIIHHHHHII',
                      0x02014b50, 20, 20, 0, 0, 0, 0, c, sz, sz, len(nb), 0, 0, 0, 0, 0, offset) + nb)
            offset += 30 + len(nb) + sz
        cd_start = offset
        cd_size = 0
        for rec in cd:
            f.write(rec); cd_size += len(rec)
        f.write(struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, len(cd), len(cd), cd_size, cd_start, 0))


def _collect(d, prefix):
    """Yield (arcname, bytes) for every file under d (one level + skips junk)."""
    out = []
    try:
        names = uos.listdir(d)
    except OSError:
        return out
    for n in names:
        full = d + '/' + n
        if _is_dir(full):
            out += _collect(full, prefix + n + '/')
            continue
        if n.endswith('.pyc') or n == '.DS_Store':
            continue
        try:
            with open(full, 'rb') as f:
                out.append((prefix + n, f.read()))
        except OSError:
            pass
    return out


def _pack(d, out):
    d = _abs(d or '.')
    if d.endswith('/.'):
        d = d[:-2] or '/'
    if not _check(d):
        warn("Fix the problems above, then pack again.")
        return
    cfg = _read_cfg(d + '/package.cfg')
    pkgname = cfg.get('pkg.name', 'package').lower()
    base = d.rsplit('/', 1)[-1] or pkgname
    out = _abs(out) if out else (_cwd() + '/' + pkgname + '.pkg')
    entries = _collect(d, base + '/')
    if not entries:
        error("Nothing to pack in '{}'.".format(d))
        return
    multi("")
    info("Packing {} file(s) -> {}".format(len(entries), out))
    try:
        _zip_stored(out, entries)
    except Exception as e:
        error("Pack failed: {}".format(e))
        return
    try:
        sz = uos.stat(out)[6]
    except OSError:
        sz = 0
    ok("Built {} ({} bytes).".format(out, sz))
    multi("  Install it:  pkg install {}".format(out))


# -- entry -----------------------------------------------------------------

def mkpkg(args=None):
    """On-device package builder."""
    a = (args or '').strip().split()
    if not a or a[0].lower() in ('help', '-h', '--help', '?'):
        info("mkpkg - build RPCortex packages on the device")
        multi("  mkpkg new <Name> [cmd]   scaffold a new package")
        multi("  mkpkg check [dir]        validate a package folder")
        multi("  mkpkg pack [dir] [out]   build an installable .pkg")
        return
    sub = a[0].lower()
    if sub == 'new':
        _new(a[1] if len(a) > 1 else '', a[2] if len(a) > 2 else '')
    elif sub == 'check':
        _check(a[1] if len(a) > 1 else '.')
    elif sub == 'pack':
        _pack(a[1] if len(a) > 1 else '.', a[2] if len(a) > 2 else '')
    else:
        warn("Unknown: {}.  Try: mkpkg new|check|pack".format(sub))


if __name__ == '__main__':
    mkpkg()
