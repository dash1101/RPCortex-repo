# Desc: Nova D1 Shell screen — the RPCortex shell, on the display.
# File: /Packages/NovaD1/novagui_shell.py
#
# Split out of novagui (the monolith de-cluttering). Binds only to the novaui leaf
# plus lazy imports; it does NOT import novagui, so the shell capture is
# re-implemented here rather than borrowed from the orchestration layer.
# See ARCHITECTURE.md. MicroPython-safe: no f-strings, .format() only.
#
# Controls, as asked for:
#   HOLD SELECT  open the keyboard and compose a command
#   SELECT       run it — the on-screen equivalent of pressing Enter
#   turn         scroll the scrollback
#   HOME         quit
#   BACK         clear the pending command (and leave if there isn't one)
#
# The scrollback is a FIXED RING, not a growing list. This device has a
# non-compacting heap and the whole reason the GUI was split apart was resident
# RAM; an unbounded transcript would be a slow leak that only shows up after a
# long session, which is the worst kind. _MAX_LINES caps it at a few screens'
# worth and old lines fall off the top.

from novaui import (Screen, ev, _TOP, _ROWH, _ADV, _SB_W, _wrap, scrollbar,
                    strip_ansi as _strip_ansi, fit as _fit)  # noqa

_MAX_LINES = 48          # ~10 screens of scrollback; older lines are dropped
# Output is wrapped once, on the way in, at the panel's character width. Wrapping
# on every draw would re-split the whole transcript 30 times a second; wrapping at
# emit time costs nothing and the panel width does not change at runtime.
_COLS = 20
_PROMPT = '> '


def run_line(cmd):
    """Run one shell line and return its output as a list of strings.

    Uses RPCortex's own capture buffer rather than swapping sys.stdout: on
    MicroPython, reassigning sys.stdout does not reliably redirect the shell's
    output, so a StringIO approach captures nothing and every command looks
    silent. This is the same lesson the Commands screen already learned."""
    import sys
    lp = sys.modules.get('launchpad') or sys.modules.get('Core.launchpad')
    if lp is None or not hasattr(lp, '_run_line'):
        return ['shell not available']
    out = ''
    try:
        import RPCortex as _R
        prev = _R.begin_capture()
        try:
            lp._run_line(cmd)
        finally:
            out = _R.end_capture(prev) or ''
    except Exception as e:
        return ['error: ' + str(e)]
    # Strip ANSI. The shell colours its output and marks each line with a tag
    # ('\x1b[96m[\x1b[97m@\x1b[96m] ...'), so raw capture text renders on the panel
    # as literal escape sequences with the marker buried in them — which is what
    # made [@] and [!] come out as garbage here while the Commands screen, which
    # has always stripped, showed them cleanly.
    out = _strip_ansi(out).replace('\r', '')
    return [ln for ln in out.split('\n')] if out.strip() else []


class ShellScreen(Screen):
    """The OS shell rendered on the panel.

    Not a terminal emulator — there is no cursor to move and no character-cell
    grid to maintain. It is a transcript plus one editable line, which is all the
    encoder and two buttons can actually drive, and it means the expensive part
    (the keyboard) only exists while you are typing."""

    def __init__(self):
        self.title = 'Shell'
        self.lines = ['RPCortex shell', 'Hold SELECT to type.']
        self.pending = ''
        self.top = 0
        self._follow = True          # stay pinned to the newest output
        self._busy = None            # a command waiting to run on the next frame
        self._frames = 0             # frames painted since _busy was queued

    # ------------------------------------------------------------------ output
    def _emit(self, text):
        """Append one line, honouring the ring cap."""
        self.lines.append(text)
        if len(self.lines) > _MAX_LINES:
            # Drop from the front in one slice rather than repeated pop(0), which
            # would rewrite the list on every append once the cap is reached.
            del self.lines[:len(self.lines) - _MAX_LINES]

    def _emit_wrapped(self, text, cols):
        for part in _wrap(str(text), cols):
            self._emit(part)

    def _cols(self, c):
        return max(1, (c.w - 4) // _ADV)

    def _visible(self, c):
        # One row is reserved at the bottom for the prompt, so the pending command
        # is always on screen no matter how far the transcript is scrolled back.
        return max(1, (c.h - _TOP) // _ROWH - 1)

    # ------------------------------------------------------------- interaction
    def _keyboard(self):
        """Open the text entry, pre-filled with whatever is pending."""
        from novagui_system import KeyboardScreen

        def done(text):
            self.pending = (text or '').strip()
            self._follow = True

        return KeyboardScreen('Command', on_done=done, initial=self.pending)

    def _submit(self, cols):
        """Queue the pending command. It runs on the next tick, not here, so the
        prompt line is repainted with the command echoed before the shell blocks —
        otherwise a slow command looks like a dead device."""
        cmd = self.pending.strip()
        if not cmd:
            return
        self._emit_wrapped(_PROMPT + cmd, cols)
        self.pending = ''
        self._busy = cmd
        self._follow = True

    # -------------------------------------------------------------------- draw
    def draw(self, c):
        vis = self._visible(c)
        n = len(self.lines)
        if self._follow:
            self.top = max(0, n - vis)
        elif self.top > max(0, n - vis):
            self.top = max(0, n - vis)
        scrolls = n > vis
        right = c.w - (_SB_W + 1) if scrolls else c.w
        for i in range(vis):
            idx = self.top + i
            if idx >= n:
                break
            _fit(c, 2, _TOP + i * _ROWH, self.lines[idx])
        if scrolls:
            scrollbar(c, right + 1, _TOP, c.h - _TOP - _ROWH, self.top, vis, n)
        # The prompt sits on the last row, separated by a rule so it reads as an
        # input rather than as more output.
        py = c.h - _ROWH
        c.hline(0, py - 1, c.w, 1)
        if self._busy:
            _fit(c, 2, py, '...')
        else:
            shown = self.pending
            # Keep the END of a long command visible: that is where the cursor
            # conceptually is, and it is the part you are still deciding about.
            avail = self._cols(c) - len(_PROMPT)
            if len(shown) > avail:
                shown = shown[len(shown) - avail:]
            _fit(c, 2, py, _PROMPT + shown)

    def tick(self, dt_ms=0):
        if self._busy is None:
            return False
        # Let one frame reach the panel before blocking on the command. The shell
        # call is synchronous and can take seconds, so without this the echoed
        # line and the '...' marker are still queued when the loop stalls and the
        # device looks dead. CommandScreen learned the same thing.
        if self._frames < 1:
            self._frames += 1
            return True
        self._frames = 0
        cmd, self._busy = self._busy, None
        try:
            out = run_line(cmd)
        except Exception as e:
            out = ['error: ' + str(e)]
        if not out:
            self._emit('(no output)')
        else:
            for ln in out:
                self._emit_wrapped(ln, _COLS)
        self._follow = True
        return True

    def on_event(self, e):
        if e == ev.SELECT_HOLD:
            return self._keyboard()
        if e == ev.SELECT:
            self._submit(_COLS)
            return None
        if e == ev.ROT_CW:
            self.top += 1
            self._follow = False
            return None
        if e == ev.ROT_CCW:
            if self.top > 0:
                self.top -= 1
            self._follow = False
            return None
        if e == ev.BACK:
            # BACK clears a half-typed command first. Leaving straight away would
            # throw the command away silently, and there is no other way to undo
            # a keyboard entry without retyping it.
            if self.pending:
                self.pending = ''
                return None
            return e
        if e == ev.HOME:
            return e
        return None
