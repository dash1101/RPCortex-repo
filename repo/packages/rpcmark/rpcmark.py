# Desc: RPCMark benchmark package for RPCortex - Vela OS
# File: /Packages/RPCMark/rpcmark.py
# Lang: MicroPython, English
# Version: v3.0.0
# Author: dash1101
#
# Shell command: bench
#
# The workloads and iteration counts match the v2 (C++) build's bench command
# exactly, and both sides score with the same formula against the same reference
# figures. Anything that differed between them would make the comparison a story
# rather than a measurement.
#
# The previous benchmark is still here, as 'bench classic'. It measures a
# different thing (mandelbrot, pi, arithmetic throughput) and its numbers are not
# comparable with v2 — which is exactly why the default changed. It lives in a
# separate module so it costs no import-time RAM unless it is asked for.

import utime

from RPCortex import info, multi, ok, warn

# Matched to os/apps/bench/bench.cpp in the v2 repo. Changing one without the
# other silently breaks the comparison, and nothing would report an error.
INT_ITER   = 200000
MEM_BYTES  = 8192
MEM_PASSES = 40
CALL_ITER  = 100000
STR_ITER   = 2000
FS_ITER    = 20

# Reference milliseconds: the time a v1.0 device is expected to take. A device
# that hits these exactly scores 200 per test, so v1.0 lands near 1000 overall
# and a score reads as "this many times a v1.0 device".
#
# These are estimates until a real v1.0 run replaces them. That does not affect
# the comparison: both builds divide by the same constants, so the RATIO between
# two scores is exact regardless. Only the 1000 anchor depends on them.
REF = {
    'integer': 18700,
    'memory':   9400,
    'function': 8100,
    'string':   6200,
    'filesys':   420,
}

# A root-level file rather than v2's /tmp/bench.tmp: v1 has no /tmp. The work is
# the same write/read/remove either way.
_TMP = '/rpcmark.tmp'

_USAGE = """bench - RPCMark, the cross-version benchmark

  bench           run the benchmark (comparable with the v2 build)
  bench classic   the older benchmark - different workload, not comparable
  bench help      this help

The score is fixed work over elapsed time, so higher is faster."""


def _bench_int():
    t0 = utime.ticks_ms()
    acc = 0
    for i in range(1, INT_ITER + 1):
        acc += i
        acc ^= (acc >> 3)
        acc += (i * 7)
        acc &= 0xFFFFFFFF          # C++ wraps at 32 bits; match it
    return utime.ticks_diff(utime.ticks_ms(), t0)


def _bench_mem():
    buf = bytearray(MEM_BYTES)
    for i in range(MEM_BYTES):
        buf[i] = i & 0xFF
    t0 = utime.ticks_ms()
    total = 0
    for _ in range(MEM_PASSES):
        for i in range(MEM_BYTES):
            total += buf[i]
    return utime.ticks_diff(utime.ticks_ms(), t0)


def _leaf(a, b):
    return a + b


def _bench_call():
    t0 = utime.ticks_ms()
    acc = 0
    for i in range(CALL_ITER):
        acc = _leaf(acc, i)
    return utime.ticks_diff(utime.ticks_ms(), t0)


def _bench_str():
    t0 = utime.ticks_ms()
    hits = 0
    for i in range(STR_ITER):
        s = "item" + str(i)
        for ch in s:
            if ch == '7':
                hits += 1
    return utime.ticks_diff(utime.ticks_ms(), t0)


def _bench_fs():
    data = b'abcdefghijklmnopqrstuvwxyz' * 10
    data = data[:256]
    t0 = utime.ticks_ms()
    for _ in range(FS_ITER):
        try:
            with open(_TMP, 'wb') as f:
                f.write(data)
            with open(_TMP, 'rb') as f:
                f.read()
            import uos
            uos.remove(_TMP)
        except OSError:
            break
    return utime.ticks_diff(utime.ticks_ms(), t0)


def _score(ms, ref):
    if ms <= 0:
        ms = 1
    return (ref * 200) // ms


def _run():
    multi("")
    multi("=== RPCMark ===")
    multi("Same workload as the C++ build, so the numbers compare.")
    multi("")
    multi("  {:<12} {:>9}   {:>5}".format("TEST", "TIME", "SCORE"))
    multi("  " + "-" * 30)

    total = 0
    for name, fn in (('integer',  _bench_int),
                     ('memory',   _bench_mem),
                     ('function', _bench_call),
                     ('string',   _bench_str),
                     ('filesys',  _bench_fs)):
        ms = fn()
        sc = _score(ms, REF[name])
        total += sc
        multi("  {:<12} {:>6} ms   {:>5}".format(name, ms, sc))

    multi("  " + "-" * 30)
    multi("  {:<12} {:>9}   {:>5}".format("TOTAL", "", total))
    multi("")
    multi("  Run 'bench' on a v2 device for its number.")
    multi("")


def bench(args=None):
    args = (args or '').strip()
    sub = args.split(None, 1)[0].lower() if args else ''

    if sub in ('help', '-h', '--help', '?'):
        for line in _USAGE.split('\n'):
            multi("  " + line)
        return

    if sub == 'classic':
        # Lazy: the classic suite is only loaded when asked for, so the common
        # path does not pay for it.
        info("Running the classic benchmark - not comparable with v2.")
        try:
            import rpcmark_classic
        except ImportError:
            warn("Classic benchmark not installed.")
            return
        rpcmark_classic.run()
        return

    if sub:
        warn("Unknown option '{}'.  Try 'bench help'.".format(sub))
        return

    info("Running RPCMark - this takes a little while.")
    _run()
    ok("Benchmark complete.")
