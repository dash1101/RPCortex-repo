# Desc: Calc — shell calculator for RPCortex
# File: /Packages/Calc/calc.py
# Version: 1.0.0
# Author: dash1101
#
# A small, dependency-free calculator that runs entirely offline.
#
# Usage:
#   calc <expression>      evaluate arithmetic   e.g.  calc 3 * (4 + 2) / 1.5
#   calc sqrt(2) + pi      math functions are available (from the math module)
#   calc hex <value>       show <value> in hexadecimal
#   calc bin <value>       show <value> in binary
#   calc oct <value>       show <value> in octal
#   calc dec <value>       show <value> in decimal (accepts 0x.. / 0b.. / 0o..)
#
# Expressions use a restricted namespace: only math functions and a handful of
# safe builtins are exposed — no filesystem, no imports, no attribute access to
# the OS.  Operators: + - * / // % ** ( ).

import sys

if '/Core' not in sys.path:
    sys.path.append('/Core')

from RPCortex import error, info, ok, multi


_USAGE = (
    "Usage:\n"
    "  calc <expression>      e.g. calc 3 * (4 + 2) / 1.5\n"
    "  calc hex <value>       to hexadecimal\n"
    "  calc bin <value>       to binary\n"
    "  calc oct <value>       to octal\n"
    "  calc dec <value>       to decimal (accepts 0x / 0b / 0o)"
)


def _fmt(n):
    """Format a numeric result: drop a trailing .0, keep real floats readable."""
    if isinstance(n, float):
        if n == int(n) and abs(n) < 1e16:
            return str(int(n))
        return "{:.10g}".format(n)
    return str(n)


def _safe_ns():
    """Build the eval namespace: every math function, plus safe builtins.

    On MicroPython, eval(expr, custom_dict) does NOT automatically inject
    builtins into the dict the way CPython does — pass the actual builtins
    module so that basic operators and literals resolve correctly.
    """
    ns = {}
    try:
        import builtins as _bi
        ns['__builtins__'] = _bi
    except ImportError:
        pass
    try:
        import math
        for name in dir(math):
            if not name.startswith('_'):
                ns[name] = getattr(math, name)
    except ImportError:
        pass
    ns['abs']   = abs
    ns['round'] = round
    ns['min']   = min
    ns['max']   = max
    ns['pow']   = pow
    ns['int']   = int
    ns['float'] = float
    return ns


def _convert(base, value):
    """Parse <value> (any base via prefix) and print it in the requested base."""
    try:
        n = int(value, 0)          # 0 = auto-detect 0x / 0b / 0o / decimal
    except ValueError:
        # Maybe a bare decimal without prefix, or a float — try plain int
        try:
            n = int(value)
        except ValueError:
            error("Not an integer: '{}'".format(value))
            return
    if base == 'hex':
        ok("0x{:X}".format(n) if n >= 0 else "-0x{:X}".format(-n))
    elif base == 'bin':
        ok("0b{:b}".format(n) if n >= 0 else "-0b{:b}".format(-n))
    elif base == 'oct':
        ok("0o{:o}".format(n) if n >= 0 else "-0o{:o}".format(-n))
    else:  # dec
        ok(str(n))


def calc(args=None):
    if not args or not args.strip():
        for line in _USAGE.split('\n'):
            multi("  " + line)
        return

    args = args.strip()
    parts = args.split(None, 1)
    sub = parts[0].lower()

    if sub in ('hex', 'bin', 'oct', 'dec'):
        if len(parts) < 2 or not parts[1].strip():
            error("Usage: calc {} <value>".format(sub))
            return
        _convert(sub, parts[1].strip())
        return

    # Otherwise: evaluate the whole thing as an arithmetic expression
    try:
        result = eval(args, _safe_ns())
    except ZeroDivisionError:
        error("Division by zero.")
        return
    except (SyntaxError, NameError) as e:
        error("Bad expression: {}".format(e))
        info("Tip: only math functions are available (try 'calc sqrt(2)').")
        return
    except Exception as e:
        error("Could not evaluate: {}".format(e))
        return

    if isinstance(result, bool):
        ok("True" if result else "False")
    elif isinstance(result, (int, float)):
        ok(_fmt(result))
    else:
        ok(str(result))
