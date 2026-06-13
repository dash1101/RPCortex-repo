# Desc: IDE - a tiny in-device dev environment for RPCortex - Pulsar OS
# File: /Packages/IDE/ide.py
# Version: 0.1.0
# Author: dash1101
#
# Mixes the file explorer and the text editor into one workspace so you can
# write, edit and TEST code (packages and .rps scripts) on the device in real
# time - no host computer needed.
#
# Shell command:  ide [path]      (also: dev)
#
# A "code space" is just a folder (open another with 'o'). The pane lists its
# files; Enter/e edits, r runs (a .rps through the script engine, a .py via
# exec), and t live-tests a package: it reads package.cfg, imports the command
# module fresh, and calls it - so editing the .py then pressing t shows the new
# behaviour immediately, without 'pkg install'.
#
# Keys:
#   Up/Down (k/j)   move        Enter / e   edit the file in the text editor
#   r               run the selected file (.rps script / .py exec)
#   t               test this folder's package command (reads package.cfg)
#   n               new file (opens the editor); end name with / for a folder
#   d / Del         delete the selected entry (asks first)
#   o               open another code space (folder path)   .. / Bksp  parent
#   i               package.cfg info        R   refresh        q   quit
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys
import uos

_CY = '\x1b[96m'
_GR = '\x1b[92m'
_YL = '\x1b[93m'
_DG = '\x1b[90m'
_WH = '\x1b[97m'
_RD = '\x1b[91m'
_RV = '\x1b[7m'
_BD = '\x1b[1m'
_R  = '\x1b[0m'

_DIR_FLAG = 0x4000
_PAGE     = 14
_W        = 64


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


def _ext(name):
    i = name.rfind('.')
    return name[i + 1:].lower() if i > 0 else ''


def _alpha(ch):
    return ('A' <= ch <= 'Z') or ('a' <= ch <= 'z')


def _read_key():
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
    _w('\x1b[{};1H\x1b[K'.format(_PAGE + 7))
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


def _listing(d):
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


def _engine():
    return sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')


def _pause(msg='-- press any key to return to the IDE --'):
    _w('\r\n' + _YL + msg + _R)
    _read_key()


def _open_editor(path):
    try:
        if '/Packages/Editor' not in sys.path:
            sys.path.append('/Packages/Editor')
        import editor
        editor.edit(path)
        return True
    except Exception as e:
        _w(_RD + 'Editor unavailable: {}'.format(e) + _R)
        return False


def _run_file(path):
    """Run a file through the live shell (execute_file: .rps->script, .py->exec)."""
    _clear(); _w('\x1b[?25h')
    _w(_CY + _BD + 'RUN  ' + _R + _WH + path + _R + '\r\n')
    _w(_DG + ('-' * _W) + _R + '\r\n')
    lp = _engine()
    if lp is None:
        _w(_RD + 'Shell engine unavailable.' + _R)
    else:
        try:
            lp._run_line(path)
        except Exception as e:
            _w(_RD + '\r\nError: {}'.format(e) + _R)
    _w('\r\n' + _DG + ('-' * _W) + _R)
    _pause(); _w('\x1b[?25l'); _clear()


def _read_cfg(cwd):
    """Return the package.cfg dict for the current folder, or None."""
    p = _join(cwd, 'package.cfg')
    if not _exists(p):
        return None
    cfg = {}
    try:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line.startswith('pkg.') and ':' in line:
                    k, v = line.split(':', 1)
                    cfg[k.strip()] = v.strip()
    except OSError:
        return None
    return cfg


def _test_package(cwd):
    """Live-test the folder's package command: import its module fresh and call
    the entry function with prompted args - no 'pkg install' needed."""
    cfg = _read_cfg(cwd)
    if not cfg or 'pkg.cmd' not in cfg:
        return "No package.cfg with a pkg.cmd here."
    entry = cfg['pkg.cmd'].split(';')[0]
    parts = entry.split(':')
    if len(parts) < 3:
        return "Malformed pkg.cmd."
    cmd, modpath, func = parts[0], parts[1], parts[2]
    # Prefer the .py beside the cfg so you test the SOURCE you're editing.
    base = modpath.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    src = _join(cwd, base + '.py')
    if not _exists(src):
        src = modpath if _exists(modpath) else None
    if not src:
        return "Module '{}.py' not found in this folder.".format(base)

    _w('\x1b[?25h')
    args = _prompt("Test '{}'  args (blank = none):".format(cmd))
    _clear()
    _w(_CY + _BD + 'TEST  ' + _R + _WH + cmd + _R + _DG + '   (' + src + ')' + _R + '\r\n')
    _w(_DG + ('-' * _W) + _R + '\r\n')
    try:
        if cwd not in sys.path:
            sys.path.append(cwd)
        # Fresh import each test so edits take effect.
        if base in sys.modules:
            del sys.modules[base]
        mod = __import__(base)
        fn = getattr(mod, func, None)
        if fn is None:
            _w(_RD + "Function '{}' not found in {}.py".format(func, base) + _R)
        else:
            fn(args if args else None)
    except Exception as e:
        _w(_RD + '\r\nError: {}'.format(e) + _R)
    _w('\r\n' + _DG + ('-' * _W) + _R)
    _pause(); _w('\x1b[?25l'); _clear()
    return "Tested '{}'.".format(cmd)


def _draw(cwd, items, sel, top, cfg, status):
    _w('\x1b[H')
    title = ' RPCortex IDE '
    tag = ('  [pkg: ' + cfg.get('pkg.name', '?') + ' v' + cfg.get('pkg.ver', '?') + ']') if cfg else ''
    right = cwd
    pad = max(1, _W - len(title) - len(tag) - len(right))
    _w(_CY + _BD + title + _R + _YL + tag + _R + _DG + ' ' * pad + right + _R + '\x1b[K\r\n')
    _w(_DG + ('-' * _W) + _R + '\x1b[K\r\n')

    if not items:
        _w(_DG + '  (empty - press n to make a file)' + _R + '\x1b[K\r\n')
        shown = 1
    else:
        shown = 0
        for i in range(top, min(top + _PAGE, len(items))):
            name, is_dir = items[i]
            label = (name + '/') if is_dir else name
            ex = _ext(name)
            tagc = _GR if is_dir else (_YL if ex in ('rps', 'py') else _WH)
            kind = 'dir' if is_dir else (ex or '-')
            row = '  {:<44} {:>6}'.format(label[:44], kind)
            if i == sel:
                _w(_RV + _WH + row + _R + '\x1b[K\r\n')
            else:
                _w(tagc + row + _R + '\x1b[K\r\n')
            shown += 1
    for _ in range(_PAGE - shown):
        _w('\x1b[K\r\n')

    _w(_DG + ('-' * _W) + _R + '\x1b[K\r\n')
    hint = 'Enter edit  r run  t test-pkg  n new  d del  o open  i info  q quit'
    _w(_DG + ' ' + hint + _R + '\x1b[K\r\n')
    _w(_YL + ' ' + (status or '') + _R + '\x1b[K')


def ide(args=None):
    """In-device IDE: browse, edit, run and live-test code."""
    cwd = (args or '').strip()
    if not cwd or not _is_dir(cwd):
        try:
            cwd = uos.getcwd()
        except Exception:
            cwd = '/'
    items = _listing(cwd)
    cfg = _read_cfg(cwd)
    sel = top = 0
    status = ''
    _clear(); _w('\x1b[?25l')

    def _reload(path):
        return _listing(path), _read_cfg(path)

    try:
        while True:
            if sel < top:
                top = sel
            elif sel >= top + _PAGE:
                top = sel - _PAGE + 1
            _draw(cwd, items, sel, top, cfg, status)
            status = ''
            key = _read_key()

            if key == 'q':
                break
            elif key in ('UP', 'k'):
                if items:
                    sel = (sel - 1) % len(items)
            elif key in ('DOWN', 'j'):
                if items:
                    sel = (sel + 1) % len(items)
            elif key in ('BKSP', 'LEFT'):
                nd = _parent(cwd)
                if nd != cwd:
                    cwd = nd; items, cfg = _reload(nd); sel = top = 0

            elif key in ('ENTER', 'e', 'RIGHT') and items:
                name, is_dir = items[sel]
                target = _join(cwd, name)
                if is_dir and key != 'e':
                    cwd = target; items, cfg = _reload(target); sel = top = 0
                elif not is_dir:
                    _open_editor(target)
                    items, cfg = _reload(cwd); _clear()

            elif key == 'r' and items:
                name, is_dir = items[sel]
                if not is_dir:
                    _run_file(_join(cwd, name))
                else:
                    status = 'Select a file to run.'

            elif key == 't':
                status = _test_package(cwd)
                items, cfg = _reload(cwd)

            elif key == 'i':
                cfg = _read_cfg(cwd)
                if cfg:
                    status = '{} v{}  cmd={}'.format(
                        cfg.get('pkg.name', '?'), cfg.get('pkg.ver', '?'),
                        cfg.get('pkg.cmd', '-').split(':')[0])
                else:
                    status = 'No package.cfg in this code space.'

            elif key == 'o':
                _w('\x1b[?25h')
                dest = _prompt('Open code space (folder path):')
                _w('\x1b[?25l')
                if dest and _is_dir(dest):
                    cwd = dest; items, cfg = _reload(dest); sel = top = 0
                elif dest:
                    status = 'Not a folder: ' + dest
                _clear()

            elif key == 'n':
                _w('\x1b[?25h')
                nm = _prompt('New (end with / for a folder):')
                _w('\x1b[?25l')
                if nm:
                    tg = _join(cwd, nm.rstrip('/'))
                    try:
                        if nm.endswith('/'):
                            uos.mkdir(tg); status = "Created folder '{}'.".format(nm.rstrip('/'))
                        else:
                            if not _exists(tg):
                                with open(tg, 'w'):
                                    pass
                            _open_editor(tg)
                        items, cfg = _reload(cwd)
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
                        items, cfg = _reload(cwd)
                        if sel >= len(items):
                            sel = max(0, len(items) - 1)
                        status = "Deleted '{}'.".format(name)
                    except Exception as e:
                        status = 'Delete failed: {}'.format(e)
                _clear()

            elif key in ('R', 'r') and not items:
                items, cfg = _reload(cwd); status = 'Refreshed.'
    finally:
        _w('\x1b[?25h'); _clear()
        _w(_DG + 'IDE closed.' + _R + '\r\n')


if __name__ == '__main__':
    ide()
