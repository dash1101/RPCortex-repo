#!/usr/bin/env python3
# Run every Nova D1 test (test_*.py) and summarise. Zero deps: `python3 run_all.py`.
# These exercise the REAL package logic (parsers/encoders/formats) under CPython
# with the hardware stubbed — the safety net for the growing codebase.
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
tests = sorted(f for f in os.listdir(HERE) if f.startswith('test_') and f.endswith('.py'))
py = sys.executable
fails = 0
print('=== Nova D1 test suite ===')
for f in tests:
    r = subprocess.run([py, os.path.join(HERE, f)], cwd=HERE,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = r.stdout.decode('utf-8', 'replace').rstrip()
    print(out)
    if r.returncode != 0:
        fails += 1
print('===', ('ALL PASS' if not fails else '{} FILE(S) FAILED'.format(fails)),
      '({} files) ==='.format(len(tests)))
sys.exit(1 if fails else 0)
