# Desc: Nova D1 Resources screen — a live readout of what the device is doing.
# File: /Packages/NovaD1/novagui_res.py
#
# Split out of novagui (the monolith de-cluttering). Binds only to the novaui leaf
# plus lazy hardware/service imports, never to novagui orchestration.
# See ARCHITECTURE.md. MicroPython-safe: no f-strings, .format() only.
#
# Every value here is read on a timer, not cached from boot — the point of the
# screen is to answer "what is it doing RIGHT NOW", and a stale number is worse
# than no number. The reads are deliberately cheap: nothing here starts a scan,
# brings up a radio, or walks the filesystem. Nearby-device counts come from the
# observer's existing cache, so opening Resources costs nothing extra; if the
# observer is off, the row says so rather than quietly showing zero.

from novaui import Screen, ev, _TOP, _ROWH, _SB_W, scrollbar, fit as _fit  # noqa

_REFRESH_MS = 1000


def _kb(n):
    """Bytes -> a short human string. Values here span 1 KB to 8 MB."""
    try:
        n = int(n)
    except Exception:
        return '?'
    if n < 1024:
        return '{}B'.format(n)
    if n < 1024 * 1024:
        return '{}K'.format(n // 1024)
    return '{:.1f}M'.format(n / (1024.0 * 1024.0))


def _pair(used, total):
    """'used/total' sharing one unit suffix, e.g. '118/264K'.

    The panel is 20 characters wide. Spelling both figures out in full ('118 KB /
    264 KB') does not fit beside its label, and the row then gets trimmed —
    which on a used/total reading silently drops the digits that matter. One
    suffix, chosen from the larger number so both are on the same scale."""
    try:
        used, total = int(used), int(total)
    except Exception:
        return '?'
    if total >= 1024 * 1024:
        div, unit = 1024.0 * 1024.0, 'M'
        return '{:.1f}/{:.1f}{}'.format(used / div, total / div, unit)
    if total >= 1024:
        return '{}/{}K'.format(used // 1024, total // 1024)
    return '{}/{}B'.format(used, total)


def _pct(used, total):
    try:
        return int(used * 100 / total) if total else 0
    except Exception:
        return 0


def _mem():
    """(free, used, total, largest_free_block). All bytes, 0 when unavailable.

    The largest block matters more than the free total on this device: the heap is
    non-compacting, so a fragmented 200 KB free can still refuse a 16 KB TLS
    buffer. Showing both is the difference between "low memory" and "fragmented",
    which are different problems with different fixes."""
    try:
        import gc
        gc.collect()
        free = gc.mem_free()
        used = gc.mem_alloc()
    except Exception:
        return (0, 0, 0, 0)
    # Largest block by halving probe — the same method `meminfo` uses. Each trial
    # buffer is released immediately and a collect follows, and the allocator
    # resets its free-index on collect, so this measures the heap without leaving
    # a mark on it. At most ~8 attempts.
    largest = 0
    size = 131072
    while size >= 512:
        try:
            probe = bytearray(size)
            del probe
            largest = size
            break
        except MemoryError:
            size //= 2
    try:
        gc.collect()
    except Exception:
        pass
    return (free, used, free + used, largest)


def _storage():
    """(used, total) bytes of the filesystem, or (0, 0) if it can't be read."""
    try:
        import uos as os
    except ImportError:
        import os
    try:
        st = os.statvfs('/')
        bs, total, avail = st[0], st[2], st[3]
        return ((total - avail) * bs, total * bs)
    except Exception:
        return (0, 0)


def _wifi():
    """(state, ssid, ip, rssi). Never brings an interface up to answer."""
    try:
        import network
        w = network.WLAN(network.STA_IF)
        if not w.active():
            return ('off', '', '', None)
        if not w.isconnected():
            return ('searching', '', '', None)
        ssid = ''
        try:
            ssid = w.config('essid') or ''
        except Exception:
            pass
        ip = ''
        try:
            ip = w.ifconfig()[0]
        except Exception:
            pass
        rssi = None
        try:
            rssi = w.status('rssi')
        except Exception:
            pass
        return ('up', ssid, ip, rssi)
    except Exception:
        return ('n/a', '', '', None)


def _nearby():
    """How many devices the observer has heard, as a display string.

    Reads the observer's stored results only. Starting a scan from a readout
    screen would turn opening Resources into a radio event, which is exactly the
    kind of hidden cost the privacy work was about."""
    try:
        import novawatch
        if not novawatch.enabled():
            return 'observer off'
        total = novawatch.count()
        if not total:
            return 'none yet' if novawatch.started() else 'starting'
        here = sum(1 for rec in novawatch.devices() if not rec.get('gone'))
        return '{} of {}'.format(here, total)
    except Exception:
        return 'n/a'


def _incognito():
    try:
        import novastealth
        return 'ON' if novastealth.active() else 'off'
    except Exception:
        from novacore import reg as _r
        return 'ON' if str(_r('Apps.NovaD1_Stealth', 'off')).lower() == 'on' else 'off'


def _screen_spec(c):
    """Panel size and type. The size comes from the live canvas rather than the
    configured panel, so a mis-set panel type shows as a size that disagrees."""
    from novacore import reg as _r
    kind = str(_r('Apps.NovaD1_Display', 'sh1106'))
    return '{}x{} {}'.format(c.w, c.h, kind)


def snapshot(c):
    """The rows to draw, as (label, value) pairs.

    Takes the canvas because the screen size is one of the things being reported.
    Returns plain strings — the drawing code does no formatting, so this is also
    what the host tests assert on."""
    rows = []
    state, ssid, ip, rssi = _wifi()
    if state == 'up':
        rows.append(('WiFi', ssid[:12] or 'connected'))
        rows.append(('IP', ip or '?'))
        if rssi is not None:
            rows.append(('Signal', '{} dBm'.format(rssi)))
    else:
        rows.append(('WiFi', state))
    rows.append(('Nearby', _nearby()))
    rows.append(('Incognito', _incognito()))
    rows.append(('Screen', _screen_spec(c)))
    free, used, total, largest = _mem()
    if total:
        rows.append(('RAM', _pair(used, total)))
        rows.append(('RAM used', '{}%'.format(_pct(used, total))))
        # Largest free block, not just the free total: the heap does not compact,
        # so a fragmented 200K free can still refuse a 16K TLS buffer. This row is
        # the difference between "low memory" and "fragmented".
        rows.append(('Largest', _kb(largest)))
    else:
        rows.append(('RAM', 'n/a'))
    su, stot = _storage()
    if stot:
        rows.append(('Disk', _pair(su, stot)))
        rows.append(('Disk used', '{}%'.format(_pct(su, stot))))
    else:
        rows.append(('Disk', 'n/a'))
    try:
        import novapower
        mhz = novapower.clock_mhz()
        rows.append(('CPU', '{} MHz'.format(mhz) if mhz else 'n/a'))
    except Exception:
        rows.append(('CPU', 'n/a'))
    try:
        import hwinfo
        rows.append(('Temp', hwinfo.cpu_temp_str()))
    except Exception:
        pass
    try:
        import utime
        up = utime.ticks_ms() // 1000
        rows.append(('Uptime', '{}h {:02d}m'.format(up // 3600, (up // 60) % 60)))
    except Exception:
        pass
    return rows


class ResourcesScreen(Screen):
    """Live device readout: link, neighbours, memory, storage, clock.

    One screen instead of five: the same facts were previously spread across Sys
    Check, Battery, WiFi and the shell's meminfo, and none of them updated while
    you watched. Rows scroll; the refresh is on a timer so a slow read can never
    stall the shared event loop more than once a second."""
    help = ('turn = scroll',
            'live, 1s refresh')
    def __init__(self):
        self.title = 'Resources'
        self.top = 0
        self._acc = 0
        self.rows = []

    def _visible(self, c):
        return max(1, (c.h - _TOP) // _ROWH)

    def draw(self, c):
        if not self.rows:
            self.rows = snapshot(c)
        rows = self.rows
        vis = self._visible(c)
        n = len(rows)
        if self.top > max(0, n - vis):
            self.top = max(0, n - vis)
        scrolls = n > vis
        right = c.w - (_SB_W + 1) if scrolls else c.w
        for i in range(vis):
            idx = self.top + i
            if idx >= n:
                break
            label, val = rows[idx]
            y = _TOP + i * _ROWH
            c.text(2, y, label, 1)
            vw = c.text_width(val)
            # Values are right-aligned so the column reads as a column. A value too
            # wide for what the label leaves is trimmed from the left, keeping the
            # end — for an IP or an SSID the tail is the part that distinguishes it.
            avail = right - 4 - c.text_width(label) - 4
            while val and vw > avail:
                val = val[1:]
                vw = c.text_width(val)
            c.text(right - vw - 2, y, val, 1)
        if scrolls:
            scrollbar(c, right + 1, _TOP, c.h - _TOP, self.top, vis, n)

    def tick(self, dt_ms=0):
        self._acc += dt_ms or 16
        if self._acc >= _REFRESH_MS:
            self._acc = 0
            # Drop the rows and let draw() rebuild them. The refresh needs the
            # canvas (the screen size is one of the readings) and only draw() has
            # one, so re-reading here would mean holding a canvas reference alive
            # for the life of the screen to save nothing.
            self.rows = []
            return True
        return False

    def on_event(self, e):
        if e == ev.ROT_CW:
            self.top += 1
        elif e == ev.ROT_CCW:
            self.top = max(0, self.top - 1)
        elif e in (ev.BACK, ev.HOME):
            return e
        return None
