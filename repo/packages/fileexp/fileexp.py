# Desc: TUI file explorer for RPCortex - Pulsar OS
# File: /Packages/FileExp/fileexp.py
# Version: 0.1.0  (DRAFT — staged in temp_claude for on-device testing)
# Author: dash1101
#
# A nano-style terminal file browser. Arrow-key navigation, view files, make
# and delete entries — without memorising ls/cd/rm. Needs a real serial
# terminal (PuTTY); arrow keys are unreliable in the Thonny REPL.
#
# Shell command:  files [path]      (also: fm, explorer)
#
# Keys:
#   Up / Down   (or k / j)   move the selection
#   Enter / ->  (or l)       open a folder, or view a file
#   <- / Bksp   (or h)       go up to the parent folder
#   d                        delete the selected entry (asks first)
#   n                        new folder (prompts for a name)
#   g                        go to a path (prompts)
#   r                        refresh
#   q                        quit
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys
import uos

# ── ANSI ────────────────────────────────────────────────────────────────────
_CY = '\x1b[96m'   # cyan   — headings
_GR = '\x1b[92m'   # green  — folders
_YL = '\x1b[93m'   # yellow — status
_DG = '\x1b[90m'   # gray   — rules / hints
_WH = '\x1b[97m'   # white  — selected
_RD = '\x1b[91m'   # red    — warnings
_BD = '\x1b[1m'
_RV = '\x1b[7m'    # reverse video — selection bar
_R  = '\x1b[0m'

_DIR_FLAG = 0x4000
_PAGE     = 16     # visible rows in the list viewport


def _w(s):
    sys.stdout.write(s)


def _clear():
    _w('\x1b[2J\x1b[H')


def _is_dir(path):
    try:
        return (uos.stat(path)[0] & _DIR_FLAG) != 0
    except OSError:
        return False


def _fmt_size(n):
    if n < 1024:
        return "{}B".format(n)
    if n < 1024 * 1024:
        return "{}K".format(n // 1024)
    return "{}M".format(n // (1024 * 1024))


def _join(d, name):
    if d == '/':
        return '/' + name
    return d.rstrip('/') + '/' + name


def _parent(d):
    d = d.rstrip('/')
    if not d:
        return '/'
    i = d.rfind('/')
    return d[:i] if i > 0 else '/'


def _listing(d):
    """Return a sorted list of (name, is_dir, size) — folders first."""
    out = []
    try:
        names = uos.listdir(d)
    except OSError:
        return out
    dirs = []
    files = []
    for n in names:
        full = _join(d, n)
        try:
            st = uos.stat(full)
            if st[0] & _DIR_FLAG:
                dirs.append((n, True, 0))
            else:
                files.append((n, False, st[6]))
        except OSError:
            files.append((n, False, 0))
    dirs.sort(key=lambda e: e[0].lower())
    files.sort(key=lambda e: e[0].lower())
    out.extend(dirs)
    out.extend(files)
    return out


def _read_key():
    """Blocking read of one logical key. Arrows -> 'UP'/'DOWN'/'LEFT'/'RIGHT'."""
    c = sys.stdin.read(1)
    if c == '\x1b':
        seq = sys.stdin.read(2)
        return {'[A': 'UP', '[B': 'DOWN', '[C': 'RIGHT', '[D': 'LEFT'}.get(seq, 'ESC')
    if c in ('\r', '\n'):
        return 'ENTER'
    if c in ('\x7f', '\x08'):
        return 'BKSP'
    if c == '\x03':
        return 'q'           # Ctrl+C exits cleanly
    return c


def _prompt(label):
    """Single-line input at the bottom of the screen."""
    _w('\x1b[{};1H\x1b[K'.format(_PAGE + 6))
    _w(_YL + label + _R + ' ')
    buf = ''
    while True:
        c = sys.stdin.read(1)
        if c in ('\r', '\n'):
            break
        if c in ('\x7f', '\x08'):
            if buf:
                buf = buf[:-1]
                _w('\x08 \x08')
            continue
        if c == '\x03':
            return ''
        buf += c
        _w(c)
    return buf.strip()


def _view_file(path):
    """Show up to 8 KB of a file, then wait for a key."""
    _clear()
    _w(_CY + _BD + 'VIEW  ' + _R + _WH + path + _R + '\r\n')
    _w(_DG + ('-' * 60) + _R + '\r\n')
    try:
        with open(path, 'r') as f:
            data = f.read(8192)
        _w(data.replace('\n', '\r\n'))
        if len(data) == 8192:
            _w('\r\n' + _DG + '... (truncated at 8 KB)' + _R)
    except Exception as e:
        _w(_RD + 'Cannot read: {}'.format(e) + _R)
    _w('\r\n' + _DG + ('-' * 60) + _R + '\r\n')
    _w(_YL + 'Press any key to return...' + _R)
    _read_key()


def _draw(cwd, entries, sel, top, status):
    _w('\x1b[H')                                   # home, no full clear (less flicker)
    _w(_CY + _BD + ' RPCortex Files ' + _R +
       _DG + '  ' + cwd + _R + '\x1b[K\r\n')
    _w(_DG + ('-' * 60) + _R + '\x1b[K\r\n')

    if not entries:
        _w(_DG + '  (empty folder)' + _R + '\x1b[K\r\n')
        shown = 0
    else:
        shown = 0
        for i in range(top, min(top + _PAGE, len(entries))):
            name, is_dir, size = entries[i]
            label = (name + '/') if is_dir else name
            meta  = 'DIR' if is_dir else _fmt_size(size)
            row = '  {:<40} {:>8}'.format(label[:40], meta)
            if i == sel:
                _w(_RV + _WH + row + _R + '\x1b[K\r\n')
            else:
                col = _GR if is_dir else _R
                _w(col + row + _R + '\x1b[K\r\n')
            shown += 1

    # pad to a stable height
    for _ in range(_PAGE - shown):
        _w('\x1b[K\r\n')

    _w(_DG + ('-' * 60) + _R + '\x1b[K\r\n')
    _w(_DG + ' Up/Down move  Enter open  <- up  d del  n new  g goto  r refresh  q quit' + _R + '\x1b[K\r\n')
    _w(_YL + ' ' + (status or '') + _R + '\x1b[K')


def files(args=None):
    """TUI file explorer entry point."""
    cwd = (args or '').strip()
    if not cwd:
        try:
            cwd = uos.getcwd()
        except Exception:
            cwd = '/'
    if not _is_dir(cwd):
        cwd = '/'

    entries = _listing(cwd)
    sel = 0
    top = 0
    status = ''
    _clear()
    _w('\x1b[?25l')                                # hide cursor

    try:
        while True:
            # keep selection within the viewport
            if sel < top:
                top = sel
            elif sel >= top + _PAGE:
                top = sel - _PAGE + 1
            _draw(cwd, entries, sel, top, status)
            status = ''

            key = _read_key()

            if key == 'q':
                break

            elif key in ('UP', 'k'):
                if entries:
                    sel = (sel - 1) % len(entries)

            elif key in ('DOWN', 'j'):
                if entries:
                    sel = (sel + 1) % len(entries)

            elif key in ('LEFT', 'BKSP', 'h'):
                newd = _parent(cwd)
                if newd != cwd:
                    cwd = newd
                    entries = _listing(cwd)
                    sel = 0
                    top = 0

            elif key in ('ENTER', 'RIGHT', 'l'):
                if entries:
                    name, is_dir, _sz = entries[sel]
                    target = _join(cwd, name)
                    if is_dir:
                        cwd = target
                        entries = _listing(cwd)
                        sel = 0
                        top = 0
                    else:
                        _view_file(target)
                        _clear()

            elif key == 'r':
                entries = _listing(cwd)
                if sel >= len(entries):
                    sel = max(0, len(entries) - 1)
                status = 'Refreshed.'

            elif key == 'g':
                _w('\x1b[?25h')
                dest = _prompt('Go to path:')
                _w('\x1b[?25l')
                if dest and _is_dir(dest):
                    cwd = dest
                    entries = _listing(cwd)
                    sel = 0
                    top = 0
                elif dest:
                    status = 'Not a folder: ' + dest
                _clear()

            elif key == 'n':
                _w('\x1b[?25h')
                name = _prompt('New folder name:')
                _w('\x1b[?25l')
                if name:
                    try:
                        uos.mkdir(_join(cwd, name))
                        entries = _listing(cwd)
                        status = "Created '{}'.".format(name)
                    except Exception as e:
                        status = 'mkdir failed: {}'.format(e)
                _clear()

            elif key == 'd':
                if entries:
                    name, is_dir, _sz = entries[sel]
                    target = _join(cwd, name)
                    _w('\x1b[?25h')
                    ans = _prompt("Delete '{}'? (y/N):".format(name))
                    _w('\x1b[?25l')
                    if ans.lower() == 'y':
                        try:
                            if is_dir:
                                uos.rmdir(target)     # only removes empty dirs
                            else:
                                uos.remove(target)
                            entries = _listing(cwd)
                            if sel >= len(entries):
                                sel = max(0, len(entries) - 1)
                            status = "Deleted '{}'.".format(name)
                        except Exception as e:
                            status = 'Delete failed: {}'.format(e)
                    else:
                        status = 'Cancelled.'
                    _clear()
    finally:
        _w('\x1b[?25h')                            # restore cursor
        _clear()
        _w(_DG + 'Closed file explorer.' + _R + '\r\n')


if __name__ == '__main__':
    files()
