# Desc: SysMon — Live system monitor for RPCortex
# File: /Packages/SysMon/sysmon.py
# Version: 2.1.0
# Author: dash1101
#
# Full-screen live dashboard. Auto-refreshes every 3s.
# Panels: Header · CPU/Uptime · Memory bars · Network · System · Logs
#
# Keys (while running):
#   r / Enter  refresh immediately
#   l          toggle log tail panel
#   n          toggle network detail
#   q / Ctrl+C quit

import sys
import gc
import utime

if '/Core' not in sys.path:
    sys.path.append('/Core')

# ANSI helpers
_R  = '\x1b[0m'
_CY = '\x1b[96m'   # bright cyan  — section headers
_GR = '\x1b[92m'   # bright green — ok / low usage
_YL = '\x1b[93m'   # yellow       — medium
_RD = '\x1b[91m'   # red          — high / error
_DG = '\x1b[90m'   # dark gray    — borders
_WH = '\x1b[97m'   # bright white — title
_BD = '\x1b[1m'    # bold
_MG = '\x1b[95m'   # magenta      — log levels

_W        = 78     # display width
_BW       = 22     # progress-bar width
_COL      = 40     # two-column split

REFRESH_S = 3
_BOOT     = utime.ticks_ms()

# ---------------------------------------------------------------------------
# Stat helpers
# ---------------------------------------------------------------------------

def _uptime():
    s = utime.ticks_diff(utime.ticks_ms(), _BOOT) // 1000
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


def _get_temp():
    try:
        import machine
        m = getattr(sys.implementation, '_machine', '') or ''
        if 'RP2350' in m.upper() or sys.platform == 'rp2':
            v = machine.ADC(4).read_u16() * 3.3 / 65535
            return '{:.1f}°C'.format(27.0 - (v - 0.706) / 0.001721)
        if sys.platform == 'esp32':
            try:
                from esp32 import raw_temperature
                return '{:.1f}°C'.format((raw_temperature() - 32) * 5.0 / 9.0)
            except Exception:
                pass
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
        d = {'ip': cfg[0], 'mask': cfg[1], 'gw': cfg[2], 'dns': cfg[3]}
        try:
            d['ssid'] = wlan.config('essid')
        except Exception:
            d['ssid'] = '?'
        try:
            d['rssi'] = wlan.status('rssi')
        except Exception:
            d['rssi'] = None
        try:
            d['mac'] = ':'.join('{:02x}'.format(b) for b in wlan.config('mac'))
        except Exception:
            d['mac'] = None
        return d
    except Exception:
        return None


def _reg(key):
    try:
        import regedit
        return regedit.read(key)
    except Exception:
        return None


def _now_str():
    """Return the current local time as YYYY-MM-DD HH:MM:SS, applying TZ_Offset."""
    try:
        off = 0
        try:
            off = int(_reg('System.TZ_Offset') or 0)
        except Exception:
            pass
        t = utime.localtime(utime.time() + off * 3600) if off else utime.localtime()
        return '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
            t[0], t[1], t[2], t[3], t[4], t[5])
    except Exception:
        return 'N/A'


def _log_tail(n=5):
    """Return last n lines of /Pulsar/Logs/latest.log."""
    try:
        with open('/Pulsar/Logs/latest.log', 'r') as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]] if lines else []
    except Exception:
        return []


def _collect():
    gc.collect()
    d = {}

    try:
        import machine
        d['freq'] = '{} MHz'.format(machine.freq() // 1000000)
    except Exception:
        d['freq'] = 'N/A'

    try:
        import machine
        d['uid'] = ':'.join('{:02x}'.format(b) for b in machine.unique_id())
    except Exception:
        d['uid'] = 'N/A'

    d['temp']     = _get_temp()
    d['platform'] = sys.platform
    d['uptime']   = _uptime()

    # RAM
    free  = gc.mem_free()
    used  = gc.mem_alloc()
    total = free + used
    d['ram_free']  = free  // 1024
    d['ram_used']  = used  // 1024
    d['ram_total'] = total // 1024
    d['ram_pct']   = used * 100 // max(1, total)

    # Flash
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

    # Registry
    d['os_ver']   = _reg('Settings.Version')    or 'Unknown'
    d['codename'] = _reg('System.Codename')     or 'Pulsar'
    d['user']     = _reg('Settings.Active_User') or '?'
    d['owner']    = _reg('System.Owner')         or None
    d['tz']       = _reg('System.TZ_Offset')     or '0'
    d['device']   = _reg('System.Device_ID')     or 'pulsar'

    try:
        v = sys.implementation.version
        d['mp_ver'] = '{}.{}.{}'.format(v[0], v[1], v[2])
    except Exception:
        d['mp_ver'] = '?'

    d['wifi'] = _get_wifi()
    d['time'] = _now_str()
    return d


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _bar(pct, w=_BW):
    pct = max(0, min(100, int(pct)))
    n   = int(pct * w / 100)
    col = _GR if pct < 60 else (_YL if pct < 85 else _RD)
    return col + '█' * n + _DG + '░' * (w - n) + _R


def _div(char='═'):
    return _DG + char * _W + _R


def _sec(title):
    prefix = '══ {} '.format(title)
    rest   = '═' * max(0, _W - len(prefix))
    return _CY + prefix + _DG + rest + _R


def _row(label, val, c2_label=None, c2_val=None):
    left = '  {:<16}{}'.format(label, val)
    if c2_label is None:
        return left
    pad = max(1, _COL - len(left))
    return left + ' ' * pad + '{:<16}{}'.format(c2_label, c2_val or '')


def _rssi_bar(rssi, w=10):
    pct = max(0, min(100, int((rssi + 90) * 100 / 60)))
    n   = int(pct * w / 100)
    col = _GR if pct >= 70 else (_YL if pct >= 30 else _RD)
    lbl = 'Excellent' if pct >= 70 else ('Good' if pct >= 45 else ('Fair' if pct >= 20 else 'Poor'))
    bar = col + '█' * n + _DG + '░' * (w - n) + _R
    return '[{}]  {} dBm  {}'.format(bar, rssi, lbl)


def _colorize_log(line):
    """Colorize a log line by severity prefix."""
    s = line.lstrip()
    if s.startswith('[!]') or s.startswith('[FATAL]'):
        return _RD + line + _R
    if s.startswith('[W]') or s.startswith('[WARN]'):
        return _YL + line + _R
    if s.startswith('[*]') or s.startswith('[OK]'):
        return _GR + line + _R
    return _DG + line + _R


def _draw(d, show_log, show_net_detail, first_draw=False):
    lines = []
    a = lines.append

    # ── Title bar ──────────────────────────────────────────────────────────
    ver      = d.get('os_ver', '?')
    device   = d.get('device', 'pulsar')
    owner    = d.get('owner')
    title_r  = '{} · {}'.format(device, owner) if owner else device
    left_vis = len('  RPCortex Monitor  ·  ') + len(ver) + 2 + len(title_r)
    hints    = '[r]refresh  [l]log  [n]net  [q]quit'
    pad      = max(1, _W - left_vis - len(hints))
    a('  ' + _WH + _BD + 'RPCortex Monitor' + _R
      + '  ·  ' + _DG + ver + '  ' + title_r + _R
      + ' ' * pad + _DG + hints + _R)
    a(_div())

    # ── System ─────────────────────────────────────────────────────────────
    a(_sec('System'))
    a(_row('Platform', d.get('platform','?'),  'Device',  d.get('device','?')))
    a(_row('CPU Freq',  d.get('freq','?'),     'Temp',    d.get('temp','N/A')))
    a(_row('Uptime',    d.get('uptime','?'),   'Time',    d.get('time','N/A')))
    a(_row('User',      d.get('user','?'),     'MicroPy', d.get('mp_ver','?')))
    a(_row('UID',       d.get('uid','N/A')))
    a('')

    # ── Memory bars ────────────────────────────────────────────────────────
    a(_sec('Memory'))
    rp = d.get('ram_pct', 0)
    a('  RAM    [{}]  {}%    {} KB used / {} KB total  ({} KB free)'.format(
        _bar(rp), rp, d.get('ram_used',0), d.get('ram_total',0), d.get('ram_free',0)))

    if d.get('flash_total', 0) > 0:
        fp = d.get('flash_pct', 0)
        fu = d.get('flash_used', 0)
        ft = d.get('flash_total', 0)
        if ft >= 1024:
            a('  Flash  [{}]  {}%    {:.1f} MB used / {:.1f} MB total'.format(
                _bar(fp), fp, fu / 1024.0, ft / 1024.0))
        else:
            a('  Flash  [{}]  {}%    {} KB used / {} KB total'.format(
                _bar(fp), fp, fu, ft))
    a('')

    # ── Network ────────────────────────────────────────────────────────────
    a(_sec('Network'))
    wi = d.get('wifi')
    if wi is None:
        a('  ' + _DG + 'WiFi not connected  (use: wifi connect)' + _R)
    else:
        ssid = wi.get('ssid', '?')
        ip   = wi.get('ip',   '?')
        gw   = wi.get('gw',   '?')
        dns  = wi.get('dns',  '?')
        rssi = wi.get('rssi', None)
        mac  = wi.get('mac',  None)
        a('  Status          ' + _GR + 'Connected' + _R)
        a(_row('SSID', ssid, 'IP', ip))
        if show_net_detail:
            a(_row('Gateway', gw,   'DNS', dns))
            if mac:
                a(_row('MAC', mac, 'Mask', wi.get('mask','?')))
        if rssi is not None:
            a('  Signal          ' + _rssi_bar(rssi))
    a('')

    # ── Log tail ───────────────────────────────────────────────────────────
    if show_log:
        a(_sec('Recent Log'))
        tail = _log_tail(6)
        if tail:
            for line in tail:
                a('  ' + _colorize_log(line[:_W - 4]))
        else:
            a('  ' + _DG + '(log is empty or not accessible)' + _R)
        a('')

    a(_div())
    a(_DG + '  Refreshes every {}s  ·  r=now  l=log  n=net detail  q=quit'.format(REFRESH_S) + _R)

    # Efficient in-place refresh: full clear only on first draw.
    # Each subsequent frame homes the cursor and erases trailing chars per line
    # so prior-frame content is overwritten cleanly even when frame height changes.
    buf = []
    if first_draw:
        buf.append('\x1b[2J')
    buf.append('\x1b[H\x1b[?25l')
    for line in lines:
        buf.append(line)
        buf.append('\x1b[K\n')
    buf.append('\x1b[J')   # erase from cursor to end (handles frame shrinkage)
    sys.stdout.write(''.join(buf))


# ---------------------------------------------------------------------------
# Input / event loop
# ---------------------------------------------------------------------------

def htop(args=None):
    show_log        = False
    show_net_detail = False
    first_draw      = True

    try:
        import select
        has_select = True
    except ImportError:
        has_select = False

    try:
        while True:
            gc.collect()
            d = _collect()
            _draw(d, show_log, show_net_detail, first_draw)
            first_draw = False
            del d
            gc.collect()

            if has_select:
                t0 = utime.ticks_ms()
                ch = None
                while utime.ticks_diff(utime.ticks_ms(), t0) < REFRESH_S * 1000:
                    r, _, _ = select.select([sys.stdin], [], [], 0.2)
                    if r:
                        ch = sys.stdin.read(1)
                        break
                if ch in ('q', 'Q', '\x03', '\x04'):
                    break
                if ch in ('l', 'L'):
                    show_log = not show_log
                if ch in ('n', 'N'):
                    show_net_detail = not show_net_detail
                # r/R/Enter/timeout: just redraw
            else:
                sys.stdout.write(_DG + '\n  (no auto-refresh — r=refresh, l=log, n=net, q=quit)\n' + _R)
                ch = sys.stdin.read(1)
                if ch in ('q', 'Q', '\x03'):
                    break
                if ch in ('l', 'L'):
                    show_log = not show_log
                if ch in ('n', 'N'):
                    show_net_detail = not show_net_detail

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write('\x1b[?25h\x1b[0m\n')

    try:
        from RPCortex import ok
        ok('sysmon exited.')
    except Exception:
        pass


sysmon = htop
