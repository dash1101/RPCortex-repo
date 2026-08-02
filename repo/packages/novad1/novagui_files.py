# Desc: Nova D1 File Explorer — browse the device filesystem from the panel.
# File: /Packages/NovaD1/novagui_files.py
#
# Split out of novagui (the monolith de-cluttering). Binds only to the novaui leaf
# plus lazy imports, never to novagui orchestration.
# See ARCHITECTURE.md. MicroPython-safe: no f-strings, .format() only.
#
# READ-ONLY on purpose. Browsing and previewing cannot lose anything; deleting
# from a 128x64 panel with three buttons can, and the shell already has `rm` with
# a prompt. If delete arrives later it needs its own confirm screen, not a row on
# this one.
#
# It is also the folder picker a music player would need, which is why pick_mode
# exists: the same screen, returning a directory instead of opening files.

from novaui import (Screen, ev, _TOP, _ROWH, _SB_W, _wrap, scrollbar,
                    rounded_rect, fit as _fit)  # noqa

# One directory is read at a time and capped. A flash root with a runaway log
# directory should slow the screen down, not exhaust the heap: this device has
# ~90 KB free and a listing is a list of strings.
MAX_ENTRIES = 200

# Preview is for glancing at a config or a log tail, not for reading a file. The
# cap is on BYTES READ rather than lines, because one file with no newlines would
# otherwise pull the whole thing into RAM to find that out.
PREVIEW_BYTES = 1024

_TEXTY = ('.txt', '.md', '.cfg', '.json', '.py', '.lp', '.log', '.rps',
          '.csv', '.ini', '.sh')


def _os():
    try:
        import uos
        return uos
    except ImportError:
        import os
        return os


def _join(path, name):
    return name if path == '/' else path + '/' + name


def _parent(path):
    if path in ('', '/'):
        return '/'
    i = path.rstrip('/').rfind('/')
    return '/' if i <= 0 else path[:i]


def _is_dir(path):
    try:
        return bool(_os().stat(path)[0] & 0x4000)
    except Exception:
        return False


def _size(path):
    try:
        return _os().stat(path)[6]
    except Exception:
        return 0


def _human(n):
    if n < 1024:
        return '{}B'.format(n)
    if n < 1024 * 1024:
        return '{}K'.format(n // 1024)
    return '{:.1f}M'.format(n / (1024.0 * 1024.0))


def listing(path):
    """(name, is_dir, size) for one directory, directories first then names.

    Sorted so the order is stable between visits — an explorer whose entries move
    around between openings is unusable, and MicroPython's ilistdir order is
    whatever the filesystem hands back."""
    os = _os()
    out = []
    try:
        names = list(os.listdir(path))
    except Exception:
        return out
    names.sort()
    for nm in names[:MAX_ENTRIES]:
        full = _join(path, nm)
        d = _is_dir(full)
        out.append((nm, d, 0 if d else _size(full)))
    out.sort(key=lambda e: (not e[1], e[0].lower()))
    return out


class PreviewScreen(Screen):
    """The first kilobyte of a text file, wrapped.

    Deliberately not an editor and not a pager: the shell has both, and this is
    for answering "is this the file I meant" without leaving the panel."""
    help = ('turn = scroll',)

    def __init__(self, path):
        self.title = path.rsplit('/', 1)[-1][:14] or 'File'
        self.top = 0
        self.lines = self._read(path)

    def _read(self, path):
        try:
            with open(path, 'r') as f:
                blob = f.read(PREVIEW_BYTES)
        except Exception as e:
            return _wrap('Cannot read: ' + str(e)[:40], 20)
        if not blob:
            return ['(empty file)']
        out = []
        for ln in blob.replace('\r', '').split('\n'):
            out.extend(_wrap(ln, 20) if ln else [''])
            if len(out) > 120:                # bounded, like the byte cap
                out.append('...')
                break
        return out

    def _visible(self, c):
        return max(1, (c.h - _TOP) // _ROWH)

    def draw(self, c):
        vis = self._visible(c)
        n = len(self.lines)
        if self.top > max(0, n - vis):
            self.top = max(0, n - vis)
        for i in range(vis):
            idx = self.top + i
            if idx >= n:
                break
            _fit(c, 2, _TOP + i * _ROWH, self.lines[idx])
        if n > vis:
            scrollbar(c, c.w - _SB_W, _TOP, c.h - _TOP, self.top, vis, n)

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.top += 1
        elif e == ev.ROT_CCW:
            self.top = max(0, self.top - 1)
        elif e in (ev.BACK, ev.HOME):
            return e
        return None


class InfoScreen(Screen):
    """What a non-text file is, since previewing it would be meaningless."""
    help = ('BACK = back to the list',)

    def __init__(self, path):
        self.title = path.rsplit('/', 1)[-1][:14] or 'File'
        self.rows = [('Name', path.rsplit('/', 1)[-1]),
                     ('Size', _human(_size(path))),
                     ('Where', _parent(path))]

    def draw(self, c):
        for i, (k, v) in enumerate(self.rows):
            y = _TOP + i * _ROWH
            c.text(2, y, k, 1)
            vw = c.text_width(v)
            # Trim from the left: for a path or a filename the tail is the part
            # that tells one from another.
            avail = c.w - 4 - c.text_width(k) - 4
            while v and vw > avail:
                v = v[1:]
                vw = c.text_width(v)
            c.text(max(2, c.w - vw - 2), y, v, 1)

    def on_event(self, e):
        if e in (ev.BACK, ev.HOME, ev.SELECT):
            return e if e == ev.HOME else 'back'
        return None


class FilesScreen(Screen):
    """Browse the filesystem.

    BACK goes UP a directory rather than out of the app, which is what a file
    explorer is expected to do; it only leaves once you are at the root and press
    it again. That is the one control worth knowing here, and it is in `help`
    rather than costing a row.

    `on_pick` turns it into a folder picker: hold SELECT on a directory returns
    it to the caller instead of opening it. Nothing uses that yet — it is what a
    music player would need to choose a queue folder from, and it costs three
    lines to leave in place rather than retrofit."""
    help = ('OK = open',
            'BACK = up a level',
            'BACK at / = quit',
            'hold OK = pick here')

    def __init__(self, path='/', on_pick=None):
        self.path = path or '/'
        self.title = 'Files'
        self.on_pick = on_pick
        self.sel = 0
        self.top = 0
        self.entries = listing(self.path)
        # Set the title HERE, not only in draw(): the runner reads scr.title to
        # paint the status bar BEFORE it calls draw(), so a title computed during
        # the draw shows up one frame late — the first frame of every directory
        # would carry the previous one's name.
        self._retitle()

    def _retitle(self):
        # The current directory IS the title -- there is no room for a path row,
        # and the status bar is already there.
        base = self.path.rsplit('/', 1)[-1]
        self.title = base or '/'

    def _go(self, path):
        self.path = path
        self.entries = listing(path)
        self.sel = 0
        self.top = 0
        self._retitle()

    def _visible(self, c):
        return max(1, (c.h - _TOP) // _ROWH)

    def draw(self, c):
        self._retitle()
        vis = self._visible(c)
        n = len(self.entries)
        if not n:
            _fit(c, 2, _TOP + _ROWH, '(empty folder)')
            return
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + vis:
            self.top = self.sel - vis + 1
        scrolls = n > vis
        right = c.w - (_SB_W + 1) if scrolls else c.w
        for i in range(vis):
            idx = self.top + i
            if idx >= n:
                break
            name, isdir, size = self.entries[idx]
            y = _TOP + i * _ROWH
            inv = (idx == self.sel)
            if inv:
                rounded_rect(c, 0, y - 1, right, _ROWH, 1)
            col = 0 if inv else 1
            # A trailing '/' marks a directory. It costs one character where an
            # icon would cost a column on every row, and it survives inversion.
            label = name + '/' if isdir else name
            if isdir:
                _fit(c, 3, y, label, col)
            else:
                sz = _human(size)
                sw = c.text_width(sz)
                avail = right - sw - 8
                while label and c.text_width(label) > avail:
                    label = label[:-1]
                c.text(3, y, label, col)
                c.text(right - sw - 2, y, sz, col)
        if scrolls:
            scrollbar(c, right + 1, _TOP, c.h - _TOP, self.top, vis, n)

    def on_event(self, e):
        n = len(self.entries)
        if e == ev.ROT_CW and n:
            self.sel = (self.sel + 1) % n
        elif e == ev.ROT_CCW and n:
            self.sel = (self.sel - 1) % n
        elif e == ev.SELECT and n:
            name, isdir, _sz = self.entries[self.sel]
            full = _join(self.path, name)
            if isdir:
                self._go(full)
                return None
            low = name.lower()
            for ext in _TEXTY:
                if low.endswith(ext):
                    return PreviewScreen(full)
            return InfoScreen(full)
        elif e == ev.SELECT_HOLD:
            if self.on_pick is not None:
                try:
                    self.on_pick(self.path)
                except Exception:
                    pass
                return 'back'
        elif e == ev.BACK:
            if self.path != '/':
                self._go(_parent(self.path))
                return None
            return e                      # already at the root: leave the app
        elif e == ev.HOME:
            return e
        return None
