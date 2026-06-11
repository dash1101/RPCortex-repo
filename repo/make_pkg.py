#!/usr/bin/env python3
"""
make_pkg.py — RPCortex package builder (PC-side tool)

Creates .pkg archives using ZIP STORED compression (no compression).
STORED is required for MicroPython — zlib is not always available.
By default, this compiles .py files to .mpy via mpy-cross for optimal memory usage.

Usage:
    python make_pkg.py <source_dirs> [-o output_dir] [--raw]

Examples:
    python make_pkg.py packages/ask          # Builds a single package
    python make_pkg.py packages/             # Scans and builds all packages inside
    python make_pkg.py packages/ -o dist/    # Puts everything neatly in a dist folder
"""

import sys
import os
import zipfile
import subprocess
import tempfile
import argparse

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

def make_pkg(source_dir, out_dir, compile_py=True):
    source_dir = os.path.normpath(source_dir)

    # Parse pkg.name from package.cfg
    cfg_path = os.path.join(source_dir, 'package.cfg')
    pkg_name = os.path.basename(source_dir).lower()
    
    with open(cfg_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('pkg.name') and ':' in line:
                pkg_name = line.split(':', 1)[1].strip().strip("'\"").lower()
                break

    output_path = os.path.join(out_dir, f"{pkg_name}.pkg")
    parent = os.path.dirname(os.path.abspath(source_dir))

    print(f"\nBuilding '{pkg_name}' from {source_dir}...")
    
    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_STORED) as zf:
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in sorted(dirs) if d != '__pycache__']
            for fname in sorted(files):
                if fname.endswith('.pyc'):
                    continue
                fpath = os.path.join(root, fname)
                rel   = os.path.relpath(fpath, parent).replace('\\', '/')
                
                # Compile .py -> .mpy by default (package.cfg stays source).
                if compile_py and fname.endswith('.py'):
                    try:
                        mpy = _compile_to_mpy(fpath)
                    except Exception as e:
                        print(f"  [!] compile failed for {rel}: {e}")
                        sys.exit(1)
                    arc = rel[:-3] + '.mpy'
                    zf.write(mpy, arc)
                    try:
                        os.remove(mpy)
                    except OSError:
                        pass
                    print(f"  + {arc}  (compiled)")
                else:
                    zf.write(fpath, rel)
                    print(f"  + {rel}")

    size = os.path.getsize(output_path)
    print(f"Success: Created '{output_path}' ({size} bytes)")
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="RPCortex package builder")
    parser.add_argument("sources", nargs="+", help="Package directories or parent directories")
    parser.add_argument("-o", "--outdir", default=".", help="Output directory for the compiled .pkg files")
    parser.add_argument("--raw", action="store_true", help="Skip mpy-cross compilation and package raw .py files")
    
    args = parser.parse_args()

    # Ensure the output directory exists
    if args.outdir != "." and not os.path.exists(args.outdir):
        os.makedirs(args.outdir)

    compile_py = not args.raw
    targets = []

    # --- Auto-Discovery Logic ---
    for src in args.sources:
        src = os.path.normpath(src)
        
        if not os.path.isdir(src):
            print(f"Skipping '{src}' (not a directory).")
            continue
            
        # Case 1: It's a direct package folder
        if os.path.isfile(os.path.join(src, 'package.cfg')):
            targets.append(src)
            
        # Case 2: It's a parent folder containing packages
        else:
            found_any = False
            for item in os.listdir(src):
                subpath = os.path.join(src, item)
                if os.path.isdir(subpath) and os.path.isfile(os.path.join(subpath, 'package.cfg')):
                    targets.append(subpath)
                    found_any = True
            
            if not found_any:
                print(f"Skipping '{src}' (no package.cfg found here or in subdirectories).")

    # Remove duplicates just in case the user passed overlapping paths
    targets = list(set(targets))
    
    if not targets:
        print("\nNo valid packages found to build.")
        sys.exit(1)

    # --- Build Loop ---
    success_count = 0
    for target in targets:
        if make_pkg(target, args.outdir, compile_py):
            success_count += 1

    print(f"\n--- Build Complete ---")
    print(f"Successfully built {success_count} package(s).")