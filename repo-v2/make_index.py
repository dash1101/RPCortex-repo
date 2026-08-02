#!/usr/bin/env python3
"""
make_index.py — build the RPCortex v2 package index.

A v2 package is a single relocatable ELF object (.app) that the OS loads at
runtime. Its name, version and ABI live in an RpcAppHeader inside the file, so
this reads them straight out of the binary rather than out of a sidecar config.
There is no second place for the version to be wrong.

    ./make_index.py                 rebuild index.json from packages/
    ./make_index.py --check         verify the index matches, change nothing

Descriptions come from meta.json, keyed by package name — the one thing that is
not derivable from the binary.
"""

import argparse
import hashlib
import json
import os
import struct
import sys

HERE     = os.path.dirname(os.path.abspath(__file__))
PKG_DIR  = os.path.join(HERE, 'packages')
INDEX    = os.path.join(HERE, 'index.json')
META     = os.path.join(HERE, 'meta.json')

BASE_URL = ('https://raw.githubusercontent.com/dash1101/RPCortex-repo'
            '/main/repo-v2/packages/')

RPC_APP_MAGIC = 0x52504341        # 'RPCA'
HEADER_SECTION = '.rpc_app_header'

# ARM EABI attribute values we accept. ARMv6-M runs on both the RP2040 (M0+) and
# the RP2350 (M33), so packages are built for it and one binary serves every
# board. An ARMv7/v8-M package would hard-fault on an M0+ rather than fail
# cleanly, so it is rejected here instead of at install time on someone's device.
PORTABLE_ARCH = 'v6S-M'


def _elf_sections(data):
    """Yield (name, offset, size) for every section in a 32-bit little-endian ELF."""
    if data[:4] != b'\x7fELF' or data[4] != 1 or data[5] != 1:
        raise ValueError('not a 32-bit little-endian ELF')
    e_shoff, = struct.unpack_from('<I', data, 0x20)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', data, 0x2E)
    if not e_shoff or not e_shnum:
        raise ValueError('no section headers')

    def sh(i):
        off = e_shoff + i * e_shentsize
        name, _typ, _flags, _addr, offset, size = struct.unpack_from('<IIIIII', data, off)
        return name, offset, size

    _, strtab_off, strtab_size = sh(e_shstrndx)
    strtab = data[strtab_off:strtab_off + strtab_size]
    for i in range(e_shnum):
        name_off, offset, size = sh(i)
        end = strtab.find(b'\0', name_off)
        yield strtab[name_off:end].decode('utf-8', 'replace'), offset, size


def read_app_header(path):
    """Pull name / version / ABI out of a .app's RpcAppHeader."""
    with open(path, 'rb') as f:
        data = f.read()
    for name, offset, size in _elf_sections(data):
        if name != HEADER_SECTION:
            continue
        if size < 44:
            raise ValueError('%s is too small (%d bytes)' % (HEADER_SECTION, size))
        blob = data[offset:offset + size]
        magic, major, minor = struct.unpack_from('<IHH', blob, 0)
        if magic != RPC_APP_MAGIC:
            raise ValueError('bad magic 0x%08x — not an RPCortex package' % magic)
        app_name = blob[8:32].split(b'\0')[0].decode('utf-8', 'replace')
        version  = blob[32:44].split(b'\0')[0].decode('utf-8', 'replace')
        return app_name, version, major, minor
    raise ValueError('no %s section — was this built against rpc_app.h?' % HEADER_SECTION)


def read_arch(path):
    """The ARM architecture tag, so a non-portable package can be refused.

    Rather than decode the ULEB128 attribute encoding, this looks for the
    Tag_CPU_name string the toolchain writes into the section. The case of that
    string is not stable — GCC emits "6S-M" for cortex-m0plus but "8-M.MAIN" for
    cortex-m33 — so the comparison is case-insensitive. Getting that wrong is how
    an M33 package reported as "unknown" instead of by name.

    Unknown is still refused: failing closed is the only safe default when the
    consequence of being wrong is a hard fault on someone's device.
    """
    with open(path, 'rb') as f:
        data = f.read()
    for name, offset, size in _elf_sections(data):
        if name != '.ARM.attributes':
            continue
        blob = data[offset:offset + size].upper()
        for cand in (b'6S-M', b'6-M', b'7E-M', b'7-M', b'8-M.MAIN', b'8-M.BASE'):
            if cand in blob:
                return 'v' + cand.decode()
    return 'unknown'


def build(check_only=False):
    if not os.path.isdir(PKG_DIR):
        sys.exit('no packages/ directory at %s' % PKG_DIR)

    meta = {}
    if os.path.exists(META):
        with open(META) as f:
            meta = json.load(f)

    packages, problems = [], []
    for fname in sorted(os.listdir(PKG_DIR)):
        if not fname.endswith('.app'):
            continue
        path = os.path.join(PKG_DIR, fname)
        try:
            name, version, major, minor = read_app_header(path)
        except ValueError as e:
            problems.append('%s: %s' % (fname, e))
            continue

        arch = read_arch(path)
        if arch != PORTABLE_ARCH:
            problems.append(
                '%s: built for %s, not %s. An ARMv7/v8-M package hard-faults on '
                'an RP2040 instead of failing cleanly — rebuild it with '
                '-mcpu=cortex-m0plus.' % (fname, arch, PORTABLE_ARCH))
            continue

        blob = open(path, 'rb').read()
        info = meta.get(name, {})
        packages.append({
            'name':   name,
            'ver':    version,
            'desc':   info.get('desc', ''),
            'author': info.get('author', 'dash1101'),
            'abi':    '%d.%d' % (major, minor),
            'arch':   'armv6m',
            'size':   len(blob),
            'sha256': hashlib.sha256(blob).hexdigest(),
            'url':    BASE_URL + fname,
        })
        if not info.get('desc'):
            problems.append('%s: no description in meta.json' % name)

    index = {
        'name':       'RPCortex Package Repository',
        'format':     2,
        'maintainer': 'dash1101',
        'packages':   packages,
    }
    text = json.dumps(index, indent=2) + '\n'

    for p in problems:
        print('  ! ' + p, file=sys.stderr)

    if check_only:
        current = open(INDEX).read() if os.path.exists(INDEX) else ''
        if current != text:
            print('index.json is out of date — run make_index.py', file=sys.stderr)
            return 1
        print('index.json is up to date (%d package(s))' % len(packages))
        return 1 if problems else 0

    with open(INDEX, 'w') as f:
        f.write(text)
    print('wrote index.json — %d package(s)' % len(packages))
    for p in packages:
        print('  %-16s %-8s %6d B  %s' % (p['name'], p['ver'], p['size'], p['arch']))
    return 1 if problems else 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true',
                    help='verify index.json is current; do not write it')
    sys.exit(build(ap.parse_args().check))
