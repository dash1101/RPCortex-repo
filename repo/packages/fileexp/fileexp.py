# Desc: TUI file explorer for RPCortex - Pulsar OS
# File: /Packages/FileExp/fileexp.py
# Version: 0.3.0
# Author: dash1101
#
# A nano-style terminal file browser. Arrow-key navigation, open files in the
# text editor, search, make and delete entries - without memorising ls/cd/rm.
# Needs a real serial terminal (PuTTY); arrow keys are flaky in the Thonny REPL.
#
# Shell command:  files [path]      (also: fm, explorer)
#
# Keys:
#   Up / Down   (or k / j)   move the selection
#   Enter / ->  (or l)       open a folder, or open a file in the editor
#   v                        quick-view a file (first 8 KB), no editor
#   <- / Bksp   (or h)       go up to the parent folder
#   /                        search / filter the current folder
#   d  or  Del               delete the selected entry (asks first)
#   n                        new file (opens it in the editor), or a folder
#                            if the name ends with '/'
#   g                        go to a path (prompts)
#   r                        refresh
#   q                        quit
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys
import uos

# -- ANSI ------------------------------------------------------------------
_CY = '\x1b[96m'   # cyan   - headings
_GR = '\x1b[92m'   # green  - folders
_YL = '\x1b[93m'   # yellow - status
_DG = '\x1b[90m'   # gray   - rules / hints
_WH = '\x1b[97m'   # white  - selected
_RD = '\x1b[91m'   # red    - warnings
_BD = '\x1b[1m'
_RV = '\x1b[7m'    # reverse video - selection bar
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


def _exists(path):
    try:
        uos.stat(path)
        return True
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
    """Return (sorted [ (name, is_dir, size) ], total_file_bytes). Folders first."""
    dirs = []
    files = []
    total = 0
    try:
        names = uos.listdir(d)
    except OSError:
        return [], 0
    for n in names:
        full = _join(d, n)
        try:
            st = uos.stat(full)
            if st[0] & _DIR_FLAG:
                dirs.append((n, True, 0))
            else:
                files.append((n, False, st[6]))
                total += st[6]
        except OSError:
            files.append((n, False, 0))
    dirs.sort(key=lambda e: e[0].lower())
    files.sort(key=lambda e: e[0].lower())
    return dirs + files, total


def _alpha(ch):
    return ('A' <= ch <= 'Z') or ('a' <= ch <= 'z')


def _read_key():
    """Blocking read of one logical key. Decodes arrows + Home/End/Del."""
    c = sys.stdin.read(1)
    if c != '\x1b':
        if c in ('\r', '\n'):
            return 'ENTER'
        if c in ('\x7f', '\x08'):
            return 'BKSP'
        if c == '\x03':
            return 'q'           # Ctrl+C exits cleanly
        return c
    if sys.stdin.read(1) != '[':
        return 'ESC'
    seq = ''
    while True:
        ch = sys.stdin.read(1)
        seq += ch
        if _alpha(ch) or ch == '~':
            break
        if len(seq) > 6:
            break
    return {
        'A': 'UP', 'B': 'DOWN', 'C': 'RIGHT', 'D': 'LEFT',
        'H': 'HOME', 'F': 'END', '1~': 'HOME', '7~': 'HOME',
        '4~': 'END', '8~': 'END', '3~': 'DEL',
    }.get(seq, 'ESC')


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


def _open_in_editor(path):
    """Open a file in the RPCortex text editor (now the Editor package).
    Returns True if it ran."""
    try:
        if '/Packages/Editor' not in sys.path:
            sys.path.append('/Packages/Editor')
        import editor
        editor.edit(path)
        return True
    except Exception:
        return False


def _view_file(path):
    """Quick-view: show up to 8 KB of a file, then wait for a key."""
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


def _draw(cwd, entries, sel, top, status, total, flt):
    _w('\x1b[H')                                   # home, no full clear (less flicker)
    title = ' RPCortex Files '
    if flt:
        title = ' RPCortex Files  [/' + flt + '] '
    _w(_CY + _BD + title + _R + _DG + '  ' + cwd + _R + '\x1b[K\r\n')
    _w(_DG + ('-' * 60) + _R + '\x1b[K\r\n')

    if not entries:
        msg = '  (no matches)' if flt else '  (empty folder)'
        _w(_DG + msg + _R + '\x1b[K\r\n')
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

    for _ in range(_PAGE - shown):                 # pad to a stable height
        _w('\x1b[K\r\n')

    _w(_DG + ('-' * 60) + _R + '\x1b[K\r\n')
    _w(_DG + ' {} items  {} total'.format(len(entries), _fmt_size(total)) +
       _R + '\x1b[K\r\n')
    _w(_DG + ' Up/Down  Enter open  v view  / find  d/Del del  n new file/dir  g goto  r  q/Esc quit' +
       _R + '\x1b[K\r\n')
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

    all_entries, total = _listing(cwd)
    flt = ''
    entries = all_entries
    sel = 0
    top = 0
    status = ''
    _clear()
    _w('\x1b[?25l')                                # hide cursor

    def _apply_filter():
        if not flt:
            return all_entries
        f = flt.lower()
        return [e for e in all_entries if f in e[0].lower()]

    def _reload(path):
        a, t = _listing(path)
        return a, t

    try:
        while True:
            if sel < top:
                top = sel
            elif sel >= top + _PAGE:
                top = sel - _PAGE + 1
            _draw(cwd, entries, sel, top, status, total, flt)
            status = ''

            key = _read_key()

            if key in ('q', 'ESC'):
                break

            elif key in ('UP', 'k'):
                if entries:
                    sel = (sel - 1) % len(entries)

            elif key in ('DOWN', 'j'):
                if entries:
                    sel = (sel + 1) % len(entries)

            elif key == 'HOME':
                sel = 0
            elif key == 'END':
                sel = max(0, len(entries) - 1)

            elif key in ('LEFT', 'BKSP', 'h'):
                newd = _parent(cwd)
                if newd != cwd:
                    cwd = newd
                    all_entries, total = _reload(cwd)
                    flt = ''
                    entries = all_entries
                    sel = 0
                    top = 0

            elif key in ('ENTER', 'RIGHT', 'l'):
                if entries:
                    name, is_dir, _sz = entries[sel]
                    target = _join(cwd, name)
                    if is_dir:
                        cwd = target
                        all_entries, total = _reload(cwd)
                        flt = ''
                        entries = all_entries
                        sel = 0
                        top = 0
                    else:
                        if not _open_in_editor(target):
                            _view_file(target)
                        _clear()
                        all_entries, total = _reload(cwd)   # size may have changed
                        entries = _apply_filter()
                        if sel >= len(entries):
                            sel = max(0, len(entries) - 1)

            elif key == 'v':                        # quick-view (no editor)
                if entries:
                    name, is_dir, _sz = entries[sel]
                    if not is_dir:
                        _view_file(_join(cwd, name))
                        _clear()

            elif key == '/':                        # search / filter
                _w('\x1b[?25h')
                flt = _prompt('Search (blank clears):')
                _w('\x1b[?25l')
                entries = _apply_filter()
                sel = 0
                top = 0
                status = ('Filter: ' + flt) if flt else 'Filter cleared.'
                _clear()

            elif key == 'r':
                all_entries, total = _reload(cwd)
                entries = _apply_filter()
                if sel >= len(entries):
                    sel = max(0, len(entries) - 1)
                status = 'Refreshed.'

            elif key == 'g':
                _w('\x1b[?25h')
                dest = _prompt('Go to path:')
                _w('\x1b[?25l')
                if dest and _is_dir(dest):
                    cwd = dest
                    all_entries, total = _reload(cwd)
                    flt = ''
                    entries = all_entries
                    sel = 0
                    top = 0
                elif dest:
                    status = 'Not a folder: ' + dest
                _clear()

            elif key == 'n':
                _w('\x1b[?25h')
                name = _prompt('New (end name with / for a folder):')
                _w('\x1b[?25l')
                if name:
                    target = _join(cwd, name.rstrip('/'))
                    try:
                        if name.endswith('/'):
                            uos.mkdir(target)
                            status = "Created folder '{}'.".format(name.rstrip('/'))
                        else:
                            # New FILE: create it empty, then open it in the editor.
                            if not _exists(target):
                                with open(target, 'w'):
                                    pass
                            _open_in_editor(target)
                            status = "Created '{}'.".format(name)
                        all_entries, total = _reload(cwd)
                        entries = _apply_filter()
                    except Exception as e:
                        status = 'create failed: {}'.format(e)
                _clear()

            elif key in ('d', 'DEL'):
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
                            all_entries, total = _reload(cwd)
                            entries = _apply_filter()
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
