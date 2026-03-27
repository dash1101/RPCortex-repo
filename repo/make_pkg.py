#!/usr/bin/env python3
"""
make_pkg.py — RPCortex package builder (PC-side tool)

Creates .pkg archives using ZIP STORED compression (no compression).
STORED is required for MicroPython on Pico W — zlib is not always available.

Usage:
    python make_pkg.py <source_dir> [output.pkg]

The source_dir must contain a package.cfg file.

Example:
    python make_pkg.py packages/helloworld helloworld.pkg
"""

import sys
import os
import zipfile


def make_pkg(source_dir, output_path=None):
    source_dir = os.path.normpath(source_dir)
    if not os.path.isdir(source_dir):
        print("Error: '{}' is not a directory.".format(source_dir))
        sys.exit(1)

    cfg_path = os.path.join(source_dir, 'package.cfg')
    if not os.path.isfile(cfg_path):
        print("Error: No package.cfg found in '{}'.".format(source_dir))
        sys.exit(1)

    # Parse pkg.name from package.cfg
    pkg_name = os.path.basename(source_dir).lower()
    with open(cfg_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('pkg.name') and ':' in line:
                pkg_name = line.split(':', 1)[1].strip().strip("'\"").lower()
                break

    if output_path is None:
        output_path = pkg_name + '.pkg'

    dir_name = os.path.basename(source_dir)
    parent   = os.path.dirname(os.path.abspath(source_dir))

    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_STORED) as zf:
        for root, dirs, files in os.walk(source_dir):
            dirs.sort()
            for fname in sorted(files):
                fpath  = os.path.join(root, fname)
                # Archive path: dir_name/relative_path (matches pkgmgr prefix stripping)
                rel    = os.path.relpath(fpath, parent)
                rel    = rel.replace('\\', '/')
                zf.write(fpath, rel)
                print("  + {}".format(rel))

    size = os.path.getsize(output_path)
    print("\nCreated '{}' ({} bytes)".format(output_path, size))
    print("Compression: ZIP_STORED (Pico-compatible, no zlib needed)")
    print("Install on device: pkg install /path/to/{}".format(output_path))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    make_pkg(src, out)
