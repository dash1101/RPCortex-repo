#!/usr/bin/env python3
"""
make_pkg.py — RPCortex package builder (PC-side tool)

Creates .pkg archives using ZIP STORED compression (no compression).
STORED is required for MicroPython on Pico W — zlib is not always available.

Usage:
    python make_pkg.py <source_dir> [output.pkg] [--compile]

    --compile   compile each .py to .mpy (via mpy-cross) before packaging.
                Needs:  pip install mpy-cross
                The package.cfg keeps its .py command path; on the device the
                loader imports the .mpy when the .py is absent. Compiled packages
                are smaller and import faster, but can't be inspected/edited
                on-device. Module filenames must be unique across packages.

The source_dir must contain a package.cfg file.

Examples:
    python make_pkg.py packages/helloworld helloworld.pkg
    python make_pkg.py packages/ntp ntp.pkg --compile
"""

import sys
import os
import zipfile
import subprocess
import tempfile


def _compile_to_mpy(py_path):
    """Compile a .py to a temp .mpy with mpy-cross; return the temp path."""
    tmp = tempfile.mktemp(suffix='.mpy')
    r = subprocess.run(
        [sys.executable, '-m', 'mpy_cross', '-o', tmp, py_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode('utf-8', 'replace').strip()
                           or 'mpy-cross failed (is it installed? pip install mpy-cross)')
    return tmp


def make_pkg(source_dir, output_path=None, compile_py=False):
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

    parent = os.path.dirname(os.path.abspath(source_dir))

    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_STORED) as zf:
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in sorted(dirs) if d != '__pycache__']
            for fname in sorted(files):
                if fname.endswith('.pyc'):
                    continue
                fpath = os.path.join(root, fname)
                rel   = os.path.relpath(fpath, parent).replace('\\', '/')
                # Compile .py -> .mpy when requested (package.cfg stays source).
                if compile_py and fname.endswith('.py'):
                    try:
                        mpy = _compile_to_mpy(fpath)
                    except Exception as e:
                        print("  [!] compile failed for {}: {}".format(rel, e))
                        sys.exit(1)
                    arc = rel[:-3] + '.mpy'
                    zf.write(mpy, arc)
                    try:
                        os.remove(mpy)
                    except OSError:
                        pass
                    print("  + {}  (compiled)".format(arc))
                else:
                    zf.write(fpath, rel)
                    print("  + {}".format(rel))

    size = os.path.getsize(output_path)
    print("\nCreated '{}' ({} bytes)".format(output_path, size))
    print("Compression: ZIP_STORED (Pico-compatible, no zlib needed)" +
          ("  |  .py compiled to .mpy" if compile_py else ""))
    print("Install on device: pkg install /path/to/{}".format(os.path.basename(output_path)))


if __name__ == '__main__':
    argv = [a for a in sys.argv[1:]]
    compile_py = False
    if '--compile' in argv:
        compile_py = True
        argv.remove('--compile')
    if len(argv) < 1:
        print(__doc__)
        sys.exit(1)
    src = argv[0]
    out = argv[1] if len(argv) > 1 else None
    make_pkg(src, out, compile_py=compile_py)
