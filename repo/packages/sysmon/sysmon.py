# Desc: SysMon — Live system monitor for RPCortex
# File: /Packages/SysMon/sysmon.py
# Version: 1.0.0
# Author: dash1101
#
# Full-screen live dashboard. Auto-refreshes every 3s.
# Shows: CPU freq, temperature, RAM bar, flash bar, WiFi stats, system info.
#
# Usage:
#   htop       — open monitor
#   sysmon     — alias
#   r          — refresh now
#   q / Ctrl+C — quit

import sys
import gc
import time

if '/Core' not in sys.path:
    sys.path.append('/Core')

# ANSI color codes
_R  = '\x1b[0m'
_CY = '\x1b[96m'   # bright cyan  — section headers
_GR = '\x1b[92m'   # bright green — ok / low usage
_YL = '\x1b[93m'   # yellow       — medium usage / warnings
_RD = '\x1b[91m'   # red          — high usage / disconnected
_DG = '\x1b[90m'   # dark gray    — borders, hints
_WH = '\x1b[97m'   # bright white — title
_BD = '\x1b[1m'    # bold

_W   = 78    # total display width
_BW  = 22    # bar fill width
_COL = 40    # two-column split position

REFRESH_S = 3   # seconds between auto-refresh
_BOOT = time.ticks_ms()


# ---------------------------------------------------------------------------
# Stat collection
# ---------------------------------------------------------------------------

def _get_temp():
    try:
        import machine
        if sys.platform == 'rp2':
            v = machine.ADC(4).read_u16() * 3.3 / 65535
            return '{:.1f} \u00b0C'.format(27.0 - (v - 0.706) / 0.001721)
        elif sys.platform == 'esp32':
            from esp32 import raw_temperature
            return '{:.1f} \u00b0C (est)'.format((raw_temperature() - 32) * 5.0 / 9.0)
    except Exception:
        pass
    return 'N/A'


def _get_wifi():
    try:
        import network
        wlan = network.WLAN(network.STA_IF)
        if not wlan.active() or not wlan.isconnected():
            return None
        cfg = wlan.ifconfig()
        info = {'ip': cfg[0], 'mask': cfg[1], 'gw': cfg[2]}
        try:
            info['ssid'] = wlan.config('essid')
        except Exception:
            info['ssid'] = '?'
        try:
            info['rssi'] = wlan.status('rssi')
        except Exception:
            info['rssi'] = None
        return info
    except Exception:
        return None


def _uptime():
    s = time.ticks_diff(time.ticks_ms(), _BOOT) // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return '{}d {}h {}m'.format(d, h, m)
    if h:
        return '{}h {}m {}s'.format(h, m, s)
    if m:
        return '{}m {}s'.format(m, s)
    return '{}s'.format(s)


def _collect():
    gc.collect()
    d = {}

    # CPU frequency
    try:
        import machine
        d['freq'] = '{} MHz'.format(machine.freq() // 1000000)
    except Exception:
        d['freq'] = 'N/A'

    d['temp']     = _get_temp()
    d['platform'] = sys.platform
    d['uptime']   = _uptime()

    # RAM
    free = gc.mem_free()
    used = gc.mem_alloc()
    total = free + used
    d['ram_used']  = used  // 1024
    d['ram_total'] = total // 1024
    d['ram_pct']   = used * 100 // max(1, total)

    # Flash / filesystem
    try:
        import uos
        st = uos.statvfs('/')
        ft = st[0] * st[2]
        ff = st[0] * st[3]
        fu = ft - ff
        d['flash_total'] = ft // 1024
        d['flash_used']  = fu // 1024
        d['flash_pct']   = fu * 100 // max(1, ft)
    except Exception:
        d['flash_total'] = 0

    # Registry: version, codename, active user
    try:
        import regedit
        d['os_ver']   = regedit.read('Settings.Version') or 'Unknown'
        d['codename'] = regedit.read('System.Codename')  or 'Nebula'
        d['user']     = regedit.read('Settings.Active_User') or '?'
    except Exception:
        d['os_ver']   = 'Unknown'
        d['codename'] = 'Nebula'
        d['user']     = '?'

    d['mp_ver']   = '.'.join(str(x) for x in sys.implementation.version)
    d['wifi']     = _get_wifi()

    return d


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _bar(pct, w=_BW):
    """Colored fill bar. Green < 60%, yellow < 85%, red >= 85%."""
    pct = max(0, min(100, int(pct)))
    n   = int(pct * w / 100)
    col = _GR if pct < 60 else (_YL if pct < 85 else _RD)
    return col + '\u2588' * n + _DG + '\u2591' * (w - n) + _R


def _div():
    """Full-width double-line divider."""
    return _DG + '\u2550' * _W + _R


def _sec(title):
    """Cyan section header: ══ TITLE ═══..."""
    prefix = '\u2550\u2550 {} '.format(title)
    rest   = '\u2550' * max(0, _W - len(prefix))
    return _CY + prefix + _DG + rest + _R


def _row(label, val, c2_label=None, c2_val=None):
    """
    Labeled data row. Keep val plain text for correct two-column alignment.
    '  label           val                  c2_label         c2_val'
    """
    left = '  {:<16}{}'.format(label, val)
    if c2_label is None:
        return left
    pad = max(1, _COL - len(left))
    return left + ' ' * pad + '{:<16}{}'.format(c2_label, c2_val or '')


def _rssi_bar(rssi, w=10):
    """Signal strength bar with label."""
    pct = max(0, min(100, int((rssi + 90) * 100 / 60)))
    n   = int(pct * w / 100)
    if pct >= 70:
        col, lbl = _GR, 'Excellent'
    elif pct >= 45:
        col, lbl = _YL, 'Good'
    elif pct >= 20:
        col, lbl = _YL, 'Fair'
    else:
        col, lbl = _RD, 'Poor'
    bar = col + '\u2588' * n + _DG + '\u2591' * (w - n) + _R
    return '[{}]  {} dBm  {}'.format(bar, rssi, lbl)


# ---------------------------------------------------------------------------
# Full screen draw
# ---------------------------------------------------------------------------

def _draw(d):
    lines = []
    a = lines.append

    a('\x1b[2J\x1b[H\x1b[?25l')   # clear screen, cursor home, hide cursor

    # ── Title bar ──────────────────────────────────────────────────────────
    ver = d.get('os_ver', '?')
    # Left side (with ANSI): '  RPCortex Monitor  ·  <ver>'
    # Right side: '[r] refresh  [q] quit'
    left_vis  = len('  RPCortex Monitor  \u00b7  ') + len(ver)
    right_vis = len('[r] refresh  [q] quit')
    pad = max(1, _W - left_vis - right_vis)
    a('  ' + _WH + _BD + 'RPCortex Monitor' + _R
      + '  \u00b7  ' + _DG + ver + _R
      + ' ' * pad
      + _DG + '[r] refresh  [q] quit' + _R)
    a(_div())
    a('')

    # ── CPU / Uptime ───────────────────────────────────────────────────────
    a(_row('Platform', d.get('platform', '?'), 'Uptime',    d.get('uptime', '?')))
    a(_row('Frequency', d.get('freq', '?'),    'Temp',      d.get('temp', 'N/A')))
    a('')

    # ── Memory bars ────────────────────────────────────────────────────────
    rp = d.get('ram_pct', 0)
    a('  RAM    [{}]  {}%    {} / {} KB'.format(
        _bar(rp), rp, d.get('ram_used', 0), d.get('ram_total', 0)))

    if d.get('flash_total', 0) > 0:
        fp = d.get('flash_pct', 0)
        fu = d.get('flash_used', 0)
        ft = d.get('flash_total', 0)
        if ft >= 1024:
            a('  Flash  [{}]  {}%    {:.1f} / {:.1f} MB'.format(
                _bar(fp), fp, fu / 1024.0, ft / 1024.0))
        else:
            a('  Flash  [{}]  {}%    {} / {} KB'.format(_bar(fp), fp, fu, ft))

    a('')

    # ── Network ────────────────────────────────────────────────────────────
    a(_sec('Network'))
    wi = d.get('wifi')
    if wi is None:
        a('  ' + _DG + 'No WiFi  (board has no network module, or not configured)' + _R)
    else:
        ssid = wi.get('ssid', '?')
        ip   = wi.get('ip',   '?')
        gw   = wi.get('gw',   '?')
        rssi = wi.get('rssi', None)
        # Status on its own line (colored value breaks two-col alignment)
        a('  Status          ' + _GR + 'Connected' + _R)
        a(_row('SSID', ssid, 'IP', ip))
        a(_row('Gateway', gw))
        if rssi is not None:
            a('  Signal          ' + _rssi_bar(rssi))

    a('')

    # ── System ─────────────────────────────────────────────────────────────
    a(_sec('System'))
    a(_row('OS',       d.get('os_ver', '?'),   'User',    d.get('user', '?')))
    a(_row('Codename', d.get('codename', '?'), 'Runtime', 'MPy ' + d.get('mp_ver', '?')))

    a('')
    a(_div())
    a(_DG + '  Refreshes every {}s   \u00b7   r = now   \u00b7   q = quit'.format(REFRESH_S) + _R)

    sys.stdout.write('\n'.join(lines) + '\n')


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def htop(args=None):
    try:
        import select
        has_select = True
    except ImportError:
        has_select = False

    try:
        while True:
            gc.collect()
            d = _collect()
            _draw(d)
            del d
            gc.collect()

            if has_select:
                # Wait up to REFRESH_S seconds, polling for keypresses every 200ms
                t0 = time.ticks_ms()
                ch = None
                while time.ticks_diff(time.ticks_ms(), t0) < REFRESH_S * 1000:
                    r, _, _ = select.select([sys.stdin], [], [], 0.2)
                    if r:
                        ch = sys.stdin.read(1)
                        break
                if ch in ('q', 'Q', '\x03', '\x04'):
                    break
                # r/R or timeout: redraw loop
            else:
                # No select module: block until keypress
                sys.stdout.write(_DG + '\n  (no auto-refresh — any key to refresh, q to quit)\n' + _R)
                ch = sys.stdin.read(1)
                if ch in ('q', 'Q', '\x03'):
                    break

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write('\x1b[?25h\x1b[0m\n')   # restore cursor and color

    try:
        from RPCortex import ok
        ok('sysmon exited.')
    except Exception:
        pass


# Allow both 'htop' and 'sysmon' as entry points
sysmon = htop
