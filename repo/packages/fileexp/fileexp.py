# Desc: TUI file explorer for RPCortex - Vela OS
# File: /Packages/FileExp/fileexp.py
# Version: 0.5.0
# Author: dash1101
#
# A nano-style terminal file browser. Arrow-key navigation, open files in the
# text editor, search, make and delete entries - without memorising ls/cd/rm.
# Needs a real serial terminal (PuTTY); arrow keys are flaky in the Thonny REPL.
#
# Shell command:  files [path]      (also: fm, explorer)
#
# v0.5.0 — COOPERATIVE MULTITASKING. The explorer now runs on the async shell's
# event loop (entry point files_async, dispatched by launchpad), so background
# services (httpd --bg, scheduled tasks) keep running while you browse. There is
# ONE implementation: files_async. The classic sync shell runs it via
# asyncio.run, so there is no second copy of the loop to drift out of sync.
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
#   R                        rename the selected entry
#   c                        copy a file to a path/folder
#   m                        move the selected entry to a folder/path
#   p                        install the selected .pkg file
#   g                        go to a path (prompts)
#   r                        refresh
#   q  or  Esc               quit
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


def _open_in_editor(path):
    """Open a file in the RPCortex text editor (now the Editor package).
    Returns True if it ran. (Sync path — used only by the classic shell.)"""
    try:
        if '/Packages/Editor' not in sys.path:
            sys.path.append('/Packages/Editor')
        import editor
        editor.edit(path)
        return True
    except Exception:
        return False


async def _aopen_in_editor(path):
    """Open a file in the cooperative editor (edit_async) so background services
    keep running while you edit. Falls back to the sync editor if the package is
    older and has no edit_async."""
    try:
        if '/Packages/Editor' not in sys.path:
            sys.path.append('/Packages/Editor')
        import editor
        if hasattr(editor, 'edit_async'):
            await editor.edit_async(path)
        else:
            editor.edit(path)
        return True
    except Exception:
        return False


def _copy_file(src, dst):
    """Stream-copy a file in 512-byte chunks (no whole-file RAM read)."""
    with open(src, 'rb') as sf:
        with open(dst, 'wb') as df:
            while True:
                b = sf.read(512)
                if not b:
                    break
                df.write(b)


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
    _w(_DG + ' Enter open  n new  R rename  c copy  m move  d del  / find  p install.pkg  g goto  q/Esc' +
       _R + '\x1b[K\r\n')
    _w(_YL + ' ' + (status or '') + _R + '\x1b[K')


# -- cooperative (async) input: yields to the event loop between keys --------
async def _aread_key():
    """Async read of one logical key. Decodes arrows + Home/End/Del. Yields to
    the loop while waiting, so background services keep running."""
    import appkit
    c = await appkit.read_key()
    if c != '\x1b':
        if c in ('\r', '\n'):
            return 'ENTER'
        if c in ('\x7f', '\x08'):
            return 'BKSP'
        if c == '\x03':
            return 'q'           # Ctrl+C exits cleanly
        return c
    seq = await appkit.read_escape()               # full CSI/SS3 sequence or bare ESC
    if len(seq) < 3 or seq[1] not in ('[', 'O'):
        return 'ESC'
    tail = seq[2:]
    return {
        'A': 'UP', 'B': 'DOWN', 'C': 'RIGHT', 'D': 'LEFT',
        'H': 'HOME', 'F': 'END', '1~': 'HOME', '7~': 'HOME',
        '4~': 'END', '8~': 'END', '3~': 'DEL',
    }.get(tail, 'ESC')


async def _aprompt(label):
    """Single-line input at the bottom of the screen (cooperative)."""
    import appkit
    _w('\x1b[{};1H\x1b[K'.format(_PAGE + 6))
    _w(_YL + label + _R + ' ')
    buf = ''
    while True:
        c = await appkit.read_key()
        if c in ('\r', '\n'):
            break
        if c in ('\x7f', '\x08'):
            if buf:
                buf = buf[:-1]
                _w('\x08 \x08')
            continue
        if c == '\x03':
            return ''
        if c == '\x1b':
            await appkit.read_escape()
            continue
        if ord(c) >= 32:
            buf += c
            _w(c)
    return buf.strip()


async def _apause():
    import appkit
    await appkit.read_key()


async def _aview_file(path):
    """Quick-view: show up to 8 KB of a file, then wait for a key (cooperative)."""
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
    await _apause()


async def _arun_and_pause(line):
    """Clear, run a shell command via the live engine, wait for a key, restore."""
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
    _clear()
    _w('\x1b[?25h')
    if lp is None:
        _w(_RD + 'Shell engine unavailable.' + _R)
    else:
        try:
            lp._run_line(line)
        except Exception as e:
            _w(_RD + 'Error: {}'.format(e) + _R)
    _w('\r\n' + _YL + 'Press any key to return...' + _R)
    await _apause()
    _w('\x1b[?25l')
    _clear()


async def files_async(args=None):
    """TUI file explorer — cooperative entry point (runs on the async loop)."""
    cwd = (args or '').strip()
    if cwd.lower() in ('help', '-h', '--help', '?'):
        for _l in ('  files / fm / explorer - TUI file manager',
                   '    files [path]    open the explorer (default: current dir)',
                   '    arrows move  Enter open  [n] new  [R] rename  [c] copy',
                   '    [m] move  [del] delete  [p] install .pkg  [/] search  [q] quit'):
            sys.stdout.write(_l + '\r\n')
        return
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

    try:
        while True:
            if sel < top:
                top = sel
            elif sel >= top + _PAGE:
                top = sel - _PAGE + 1
            _draw(cwd, entries, sel, top, status, total, flt)
            status = ''

            key = await _aread_key()

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
                    all_entries, total = _listing(cwd)
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
                        all_entries, total = _listing(cwd)
                        flt = ''
                        entries = all_entries
                        sel = 0
                        top = 0
                    else:
                        if not await _aopen_in_editor(target):
                            await _aview_file(target)
                        _clear()
                        all_entries, total = _listing(cwd)   # size may have changed
                        entries = _apply_filter()
                        if sel >= len(entries):
                            sel = max(0, len(entries) - 1)

            elif key == 'v':                        # quick-view (no editor)
                if entries:
                    name, is_dir, _sz = entries[sel]
                    if not is_dir:
                        await _aview_file(_join(cwd, name))
                        _clear()

            elif key == '/':                        # search / filter
                _w('\x1b[?25h')
                flt = await _aprompt('Search (blank clears):')
                _w('\x1b[?25l')
                entries = _apply_filter()
                sel = 0
                top = 0
                status = ('Filter: ' + flt) if flt else 'Filter cleared.'
                _clear()

            elif key == 'r':
                all_entries, total = _listing(cwd)
                entries = _apply_filter()
                if sel >= len(entries):
                    sel = max(0, len(entries) - 1)
                status = 'Refreshed.'

            elif key == 'g':
                _w('\x1b[?25h')
                dest = await _aprompt('Go to path:')
                _w('\x1b[?25l')
                if dest and _is_dir(dest):
                    cwd = dest
                    all_entries, total = _listing(cwd)
                    flt = ''
                    entries = all_entries
                    sel = 0
                    top = 0
                elif dest:
                    status = 'Not a folder: ' + dest
                _clear()

            elif key == 'n':
                _w('\x1b[?25h')
                name = await _aprompt('New (end name with / for a folder):')
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
                            await _aopen_in_editor(target)
                            status = "Created '{}'.".format(name)
                        all_entries, total = _listing(cwd)
                        entries = _apply_filter()
                    except Exception as e:
                        status = 'create failed: {}'.format(e)
                _clear()

            elif key == 'R' and entries:        # rename in place
                name, is_dir, _sz = entries[sel]
                _w('\x1b[?25h')
                new = await _aprompt("Rename '{}' to:".format(name))
                _w('\x1b[?25l')
                if new and new != name:
                    try:
                        uos.rename(_join(cwd, name), _join(cwd, new))
                        all_entries, total = _listing(cwd); entries = _apply_filter()
                        status = "Renamed to '{}'.".format(new)
                    except Exception as e:
                        status = 'Rename failed: {}'.format(e)
                _clear()

            elif key == 'c' and entries:        # copy a file to a path/folder
                name, is_dir, _sz = entries[sel]
                if is_dir:
                    status = 'Copy is file-only (cp does not recurse).'
                else:
                    _w('\x1b[?25h')
                    dest = await _aprompt("Copy '{}' to (path or folder):".format(name))
                    _w('\x1b[?25l')
                    if dest:
                        if _is_dir(dest):
                            dest = _join(dest, name)
                        try:
                            _copy_file(_join(cwd, name), dest)
                            all_entries, total = _listing(cwd); entries = _apply_filter()
                            status = "Copied to '{}'.".format(dest)
                        except Exception as e:
                            status = 'Copy failed: {}'.format(e)
                    _clear()

            elif key == 'm' and entries:        # move (rename across folders)
                name, is_dir, _sz = entries[sel]
                _w('\x1b[?25h')
                dest = await _aprompt("Move '{}' to (folder or path):".format(name))
                _w('\x1b[?25l')
                if dest:
                    target = _join(dest, name) if _is_dir(dest) else dest
                    try:
                        uos.rename(_join(cwd, name), target)
                    except OSError:
                        # cross-filesystem: copy then remove (files only)
                        try:
                            if is_dir:
                                raise OSError('folder')
                            _copy_file(_join(cwd, name), target)
                            uos.remove(_join(cwd, name))
                        except Exception as e:
                            status = 'Move failed: {}'.format(e); target = None
                    if target:
                        all_entries, total = _listing(cwd); entries = _apply_filter()
                        if sel >= len(entries):
                            sel = max(0, len(entries) - 1)
                        status = "Moved to '{}'.".format(target)
                _clear()

            elif key == 'p' and entries:        # package: install a .pkg here
                name, is_dir, _sz = entries[sel]
                if not is_dir and name.lower().endswith('.pkg'):
                    await _arun_and_pause('pkg install ' + _join(cwd, name))
                    all_entries, total = _listing(cwd); entries = _apply_filter()
                elif is_dir and _exists(_join(_join(cwd, name), 'package.cfg')):
                    status = "Folder is a package source — build it with 'mkpkg'."
                else:
                    status = 'Select a .pkg file to install (p).'

            elif key in ('d', 'DEL'):
                if entries:
                    name, is_dir, _sz = entries[sel]
                    target = _join(cwd, name)
                    _w('\x1b[?25h')
                    ans = await _aprompt("Delete '{}'? (y/N):".format(name))
                    _w('\x1b[?25l')
                    if ans.lower() == 'y':
                        try:
                            if is_dir:
                                uos.rmdir(target)     # only removes empty dirs
                            else:
                                uos.remove(target)
                            all_entries, total = _listing(cwd)
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


def files(args=None):
    """Classic-shell entry: run the cooperative explorer on a one-shot loop.
    In the async shell, launchpad dispatches files_async directly (so background
    services keep running); this path is only used by `asyncmode off`."""
    try:
        import asyncio
    except ImportError:
        import uasyncio as asyncio
    asyncio.run(files_async(args))


if __name__ == '__main__':
    files()
