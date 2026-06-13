# Desc: Desktop - a keyboard-driven icon "desktop" for RPCortex - Pulsar OS
# File: /Packages/Desktop/desktop.py
# Version: 0.1.0
# Author: dash1101
#
# A nod to early desktop operating systems: your files are laid out as a grid
# of icons on a "desktop", and a white cursor (the highlighted icon) is moved
# with the arrow keys. Enter opens a folder, runs a runnable file (.rps / .py),
# or opens anything else in the text editor. Needs a real serial terminal
# (PuTTY) - arrow keys are flaky in the Thonny REPL.
#
# Shell command:  desktop [path]   (also: dt)
#
# Keys:
#   Up/Down/Left/Right    move the icon cursor around the grid
#   Enter                 open folder / run .rps|.py / edit other files
#   e                     edit the selected file in the text editor
#   x                     run the selected file (.rps or .py)
#   n                     new file (opens the editor); end name with / for a folder
#   Del / d               delete the selected icon (asks first)
#   Bksp / Left-at-edge   go up to the parent folder
#   r                     refresh        q   quit
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys
import uos

# -- ANSI ------------------------------------------------------------------
_CY = '\x1b[96m'   # cyan   - title bar
_GR = '\x1b[92m'   # green  - folders
_YL = '\x1b[93m'   # yellow - runnable
_DG = '\x1b[90m'   # gray   - rules / hints
_WH = '\x1b[97m'   # white  - text
_RV = '\x1b[7m'    # reverse video - the cursor/selection
_BD = '\x1b[1m'
_R  = '\x1b[0m'

_DIR_FLAG = 0x4000
_W        = 62           # desktop width
_COLS     = 4            # icons per row
_CELL     = _W // _COLS  # cell width
_ROWS     = 5            # visible icon rows (a page)


def _w(s):
    sys.stdout.write(s)


def _clear():
    _w('\x1b[2J\x1b[H')


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


def _alpha(ch):
    return ('A' <= ch <= 'Z') or ('a' <= ch <= 'z')


def _read_key():
    """Blocking read of one logical key (arrows + Del decoded)."""
    c = sys.stdin.read(1)
    if c != '\x1b':
        if c in ('\r', '\n'):
            return 'ENTER'
        if c in ('\x7f', '\x08'):
            return 'BKSP'
        if c == '\x03':
            return 'q'
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
    return {'A': 'UP', 'B': 'DOWN', 'C': 'RIGHT', 'D': 'LEFT', '3~': 'DEL'}.get(seq, 'ESC')


def _prompt(label):
    """Single-line input on the bottom row."""
    _w('\x1b[{};1H\x1b[K'.format(_ROWS * 3 + 7))
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


# -- file classification ---------------------------------------------------

_GLYPH = {'py': '.py', 'rps': 'rps', 'cfg': 'cfg', 'lp': '.lp',
          'json': 'jsn', 'log': 'log', 'mpy': 'mpy', 'txt': 'txt'}


def _ext(name):
    i = name.rfind('.')
    return name[i + 1:].lower() if i > 0 else ''


def _runnable(name):
    return _ext(name) in ('rps', 'py')


def _glyph(name, is_dir):
    if is_dir:
        return 'DIR'
    return _GLYPH.get(_ext(name), ' - ')


def _listing(d):
    """Sorted [(name, is_dir)] - folders first."""
    dirs, files = [], []
    try:
        for n in uos.listdir(d):
            if _is_dir(_join(d, n)):
                dirs.append(n)
            else:
                files.append(n)
    except OSError:
        return []
    dirs.sort(key=lambda s: s.lower())
    files.sort(key=lambda s: s.lower())
    return [(n, True) for n in dirs] + [(n, False) for n in files]


# -- engine bridge (run a file through the live shell) ---------------------

def _run_file(path):
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
    if lp is None:
        return
    try:
        lp._run_line(path)          # execute_file runs .rps via script, .py via exec
    except Exception as e:
        _w(_R + '\r\nRun error: {}\r\n'.format(e))


def _open_editor(path):
    try:
        if '/Packages/Editor' not in sys.path:
            sys.path.append('/Packages/Editor')
        import editor
        editor.edit(path)
        return True
    except Exception:
        return False


def _pause(msg='Press any key...'):
    _w('\r\n' + _YL + msg + _R)
    _read_key()


# -- drawing ---------------------------------------------------------------

def _clock():
    try:
        import time
        off = 0
        try:
            import regedit
            off = int(regedit.read('System.TZ_Offset') or 0)
        except Exception:
            off = 0
        t = time.localtime(time.time() + off * 3600)   # RTC is UTC; apply the zone
        return '{:02d}:{:02d}'.format(t[3], t[4])
    except Exception:
        return '--:--'


def _center(s, w):
    if len(s) >= w:
        return s[:w]
    pad = w - len(s)
    left = pad // 2
    return (' ' * left) + s + (' ' * (pad - left))


def _draw(cwd, items, sel, top, status):
    _w('\x1b[H')
    # --- taskbar (reverse-video, full width) ---
    left = ' ■ RPCortex Desktop '
    right = ' ' + _clock() + ' '
    mid = cwd
    space = _W - len(left) - len(right) - len(mid)
    if space < 0:
        mid = '…' + mid[len(mid) - (_W - len(left) - len(right) - 1):]
        space = _W - len(left) - len(right) - len(mid)
    _w(_RV + _CY + _BD + (left + mid + ' ' * max(0, space) + right)[:_W] + _R + '\x1b[K\r\n')
    _w('\x1b[K\r\n')   # wallpaper gap

    if not items:
        _w(_DG + '   (empty - press n to make a file or folder)' + _R + '\x1b[K\r\n')
        for _ in range(_ROWS * 3 - 1):
            _w('\x1b[K\r\n')
    else:
        page = items[top:top + _ROWS * _COLS]
        for r in range(_ROWS):
            row = page[r * _COLS:(r + 1) * _COLS]
            glyph_line = ' '
            name_line  = ' '
            for c in range(_COLS):
                gi = top + r * _COLS + c
                if c < len(row):
                    name, is_dir = row[c]
                    gl = '[' + _glyph(name, is_dir) + ']'
                    nm = name if len(name) <= _CELL - 2 else name[:_CELL - 3] + '…'
                    col = _GR if is_dir else (_YL if _runnable(name) else _WH)
                    if gi == sel:
                        glyph_line += _RV + _WH + _BD + _center(gl, _CELL) + _R
                        name_line  += _WH + _BD + _center(nm, _CELL) + _R
                    else:
                        glyph_line += col + _center(gl, _CELL) + _R
                        name_line  += _DG + _center(nm, _CELL) + _R
                else:
                    glyph_line += ' ' * _CELL
                    name_line  += ' ' * _CELL
            _w(glyph_line + '\x1b[K\r\n')
            _w(name_line + '\x1b[K\r\n')
            _w('\x1b[K\r\n')   # gap between icon rows

    _w(_DG + ('─' * _W) + _R + '\x1b[K\r\n')
    hint = status or 'arrows move   Enter open/run   e edit   x run   n new   Bksp up   q/Esc quit'
    _w(_RV + _DG + _center(hint, _W) + _R + '\x1b[K')


def desktop(args=None):
    """Keyboard-driven icon desktop."""
    cwd = (args or '').strip()
    if not cwd or not _is_dir(cwd):
        try:
            cwd = uos.getcwd()
        except Exception:
            cwd = '/'
    items = _listing(cwd)
    sel = 0
    top = 0
    status = ''
    _clear()
    _w('\x1b[?25l')                                  # hide the real cursor

    def _reload(path):
        return _listing(path)

    try:
        while True:
            # keep the selection on the visible page
            page_sz = _ROWS * _COLS
            if sel < top:
                top = (sel // _COLS) * _COLS
            elif sel >= top + page_sz:
                top = (sel // _COLS - _ROWS + 1) * _COLS
            if top < 0:
                top = 0
            _draw(cwd, items, sel, top, status)
            status = ''
            key = _read_key()

            if key in ('q', 'ESC'):
                break
            elif key == 'RIGHT':
                if items and sel < len(items) - 1:
                    sel += 1
            elif key == 'LEFT':
                if sel > 0:
                    sel -= 1
                else:
                    key = 'BKSP'            # left at the first icon goes up a level
            elif key == 'DOWN':
                if items and sel + _COLS < len(items):
                    sel += _COLS
            elif key == 'UP':
                if sel - _COLS >= 0:
                    sel -= _COLS

            if key == 'BKSP':
                nd = _parent(cwd)
                if nd != cwd:
                    cwd, items, sel, top = nd, _reload(nd), 0, 0

            elif key == 'ENTER' and items:
                name, is_dir = items[sel]
                target = _join(cwd, name)
                if is_dir:
                    cwd, items, sel, top = target, _reload(target), 0, 0
                elif _runnable(name):
                    _clear(); _w('\x1b[?25h')
                    _w(_CY + 'Running ' + name + ' ...' + _R + '\r\n\r\n')
                    _run_file(target)
                    _pause(); _w('\x1b[?25l'); _clear()
                else:
                    _open_editor(target)
                    items = _reload(cwd); _clear()

            elif key == 'e' and items:
                name, is_dir = items[sel]
                if not is_dir:
                    _open_editor(_join(cwd, name))
                    items = _reload(cwd); _clear()

            elif key == 'x' and items:
                name, is_dir = items[sel]
                if is_dir:
                    status = 'Cannot run a folder.'
                elif _runnable(name):
                    _clear(); _w('\x1b[?25h')
                    _run_file(_join(cwd, name))
                    _pause(); _w('\x1b[?25l'); _clear()
                else:
                    status = "'{}' is not runnable (.rps/.py).".format(name)

            elif key == 'n':
                _w('\x1b[?25h')
                nm = _prompt('New (end with / for a folder):')
                _w('\x1b[?25l')
                if nm:
                    tg = _join(cwd, nm.rstrip('/'))
                    try:
                        if nm.endswith('/'):
                            uos.mkdir(tg)
                            status = "Created folder '{}'.".format(nm.rstrip('/'))
                        else:
                            if not _exists(tg):
                                with open(tg, 'w'):
                                    pass
                            _open_editor(tg)
                        items = _reload(cwd)
                    except Exception as e:
                        status = 'create failed: {}'.format(e)
                _clear()

            elif key in ('d', 'DEL') and items:
                name, is_dir = items[sel]
                _w('\x1b[?25h')
                ans = _prompt("Delete '{}'? (y/N):".format(name))
                _w('\x1b[?25l')
                if ans.lower() == 'y':
                    try:
                        if is_dir:
                            uos.rmdir(_join(cwd, name))
                        else:
                            uos.remove(_join(cwd, name))
                        items = _reload(cwd)
                        if sel >= len(items):
                            sel = max(0, len(items) - 1)
                        status = "Deleted '{}'.".format(name)
                    except Exception as e:
                        status = 'Delete failed: {}'.format(e)
                _clear()

            elif key == 'r':
                items = _reload(cwd)
                if sel >= len(items):
                    sel = max(0, len(items) - 1)
                status = 'Refreshed.'
    finally:
        _w('\x1b[?25h')
        _clear()
        _w(_DG + 'Desktop closed.' + _R + '\r\n')


if __name__ == '__main__':
    desktop()
