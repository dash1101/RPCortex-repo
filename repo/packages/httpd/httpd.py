# Desc: httpd - a tiny web server for RPCortex - Pulsar OS
# File: /Packages/HTTPd/httpd.py
# Version: 0.6.0
# Author: dash1101
#
# Serve a live status dashboard + a browsable/downloadable view of the device
# filesystem over WiFi, OR host a folder of your own as a static site.
#
# Run it in the FOREGROUND (blocks until q / Ctrl+C) or — new in v0.9.5 — as a
# BACKGROUND service in the async shell, so it keeps serving while you use the
# prompt for other work. The background server is a supervised coroutine; check
# it with 'httpd status', stop it with 'httpd stop', auto-start it at login with
# 'service add "httpd start --bg"'.
#
# Shell command:
#   httpd                 open the control panel (TUI: config, logs, start)
#   httpd start [port]    serve in the foreground (q / Ctrl+C to stop)
#   httpd start --bg      serve in the background (needs 'asyncmode on')
#   httpd status          print background-server stats as text
#   httpd stop            stop the background server
#
# Routes:  /  (dashboard)   /api (JSON status)   /fs?path=/  (file browser)
#          /dl?path=<file>  (download a file)
#
# SECURITY: this exposes the whole filesystem read-only to anyone on the
# network. Run it only on a trusted LAN; stop it (q) when you're done. Turn
# the file browser off (Browse files: OFF in the panel) to serve only the
# dashboard / your static site.
#
# Config (httpd.cfg, edited live by the panel):
#   port / title / serve_dir / browse
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys
import uos

from RPCortex import ok, info, warn, error, multi, inpt

_DIR_FLAG = 0x4000
_DEFAULT_PORT = 8080

# In-RAM request log (survives between panel<->server hops within a session,
# because the module stays in sys.modules). Capped so it can never grow RAM.
_LOG = []
_LOG_MAX = 40

_CTYPES = {'html': 'text/html', 'htm': 'text/html', 'css': 'text/css',
           'js': 'application/javascript', 'json': 'application/json',
           'txt': 'text/plain', 'png': 'image/png', 'jpg': 'image/jpeg',
           'jpeg': 'image/jpeg', 'gif': 'image/gif', 'svg': 'image/svg+xml',
           'ico': 'image/x-icon'}

# ANSI styling (mirrors the settings panel: borderless, cyan heads).
_CY = '\x1b[96m'; _GR = '\x1b[92m'; _YL = '\x1b[93m'
_DG = '\x1b[90m'; _WH = '\x1b[97m'; _BD = '\x1b[1m'; _R = '\x1b[0m'
_W = 78


# -- config ----------------------------------------------------------------

def _pkg_dir():
    """This package's own dir (case-insensitive) — where httpd.cfg lives."""
    try:
        for e in uos.listdir('/Packages'):
            if e.lower() == 'httpd':
                return '/Packages/' + e
    except OSError:
        pass
    return '/Packages/HTTPd'


def _load_cfg():
    """Read httpd.cfg (key: value lines) from the package dir. Keys:
      port:      default listen port (8080)
      title:     dashboard heading
      serve_dir: a folder to host as a STATIC SITE (its index.html at '/');
                 blank = show the built-in dashboard
      browse:    'true' to expose the filesystem browser at /fs (default true)"""
    cfg = {'port': _DEFAULT_PORT, 'title': '', 'serve_dir': '', 'browse': 'true'}
    try:
        with open(_pkg_dir() + '/httpd.cfg') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or ':' not in line:
                    continue
                k, v = line.split(':', 1)
                k, v = k.strip().lower(), v.strip()
                if k == 'port':
                    try:
                        cfg['port'] = int(v)
                    except ValueError:
                        pass
                elif k in cfg:
                    cfg[k] = v
    except OSError:
        pass
    return cfg


def _save_cfg(cfg):
    """Write the working config back to httpd.cfg (with explanatory comments)."""
    lines = (
        '# httpd.cfg - RPCortex web server config\n'
        '# Edit here, or live via the panel:  httpd\n'
        '\n'
        '# Listen port.\n'
        'port: {}\n'
        '\n'
        '# Dashboard heading (blank = device name).\n'
        'title: {}\n'
        '\n'
        '# Folder to host as a static site (blank = built-in dashboard).\n'
        'serve_dir: {}\n'
        '\n'
        "# Expose the read-only filesystem browser at /fs ('true'/'false').\n"
        'browse: {}\n'
    ).format(cfg.get('port', _DEFAULT_PORT), cfg.get('title', ''),
             cfg.get('serve_dir', ''), cfg.get('browse', 'true'))
    try:
        with open(_pkg_dir() + '/httpd.cfg', 'w') as f:
            f.write(lines)
        return True
    except OSError:
        return False


# -- helpers ---------------------------------------------------------------

# Files that are NEVER listed or served, even with the browser on — they hold
# secrets: salted password hashes (user.cfg) and plaintext WiFi keys
# (networks.cfg). Matched by basename, case-insensitively, so the device's
# credentials can't be grabbed off the LAN by anyone who finds the server.
_SECRET_NAMES = ('user.cfg', 'networks.cfg', 'user.dat', 'shadow', 'passwd')


def _is_secret(path):
    return path.rsplit('/', 1)[-1].lower() in _SECRET_NAMES


def _is_dir(path):
    try:
        return (uos.stat(path)[0] & _DIR_FLAG) != 0
    except OSError:
        return False


def _ip():
    try:
        import net
        return net.status().get('ip', '0.0.0.0')
    except Exception:
        return '0.0.0.0'


def _online():
    try:
        import net
        if not net.is_available():
            error("WiFi not available on this board.")
            return False
        if not net.status().get('connected'):
            error("Not connected to WiFi. Run: wifi connect")
            return False
    except Exception:
        pass
    return True


def _now():
    try:
        import time
        t = time.localtime()
        return '{:02d}:{:02d}:{:02d}'.format(t[3], t[4], t[5])
    except Exception:
        return '--:--:--'


def _log(method, path, status):
    """Append a request to the in-RAM ring buffer (newest last)."""
    _LOG.append('{}  {:<4} {:<3} {}'.format(_now(), method, status, path))
    if len(_LOG) > _LOG_MAX:
        del _LOG[0:len(_LOG) - _LOG_MAX]


def _esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;'))


def _qs(path):
    """Split 'path?a=b&c=d' into (path, {a:b,...}). Minimal urldecode of %20."""
    q = {}
    if '?' in path:
        path, rest = path.split('?', 1)
        for pair in rest.split('&'):
            if '=' in pair:
                k, v = pair.split('=', 1)
                q[k] = v.replace('%2F', '/').replace('%20', ' ').replace('+', ' ')
    return path, q


# -- page builders ---------------------------------------------------------

_CSS = ("body{font-family:system-ui,sans-serif;background:#0e1116;color:#e6e6e6;"
        "margin:0;padding:24px;}a{color:#6cf;text-decoration:none}a:hover{text-decoration:underline}"
        "h1{color:#8cf}.card{background:#171c24;border:1px solid #232a35;border-radius:10px;"
        "padding:16px 20px;margin:14px 0;max-width:760px}code{color:#9f9}"
        "table{border-collapse:collapse;width:100%}td{padding:4px 10px;border-bottom:1px solid #232a35}"
        ".dim{color:#8a93a0}")


def _dashboard(cfg):
    import gc
    try:
        import regedit
        ver = regedit.read('Settings.Version') or '?'
        dev = regedit.read('System.Device_ID') or 'pulsar'
        owner = regedit.read('System.Owner') or ''
        build = regedit.read('System.Build') or 'source'
    except Exception:
        ver = dev = build = '?'; owner = ''
    title = cfg.get('title') or dev
    gc.collect()
    free = gc.mem_free() // 1024
    rows = [
        ('OS', 'RPCortex ' + ver + '  (build ' + build + ')'),
        ('Device', dev + (('  -  ' + owner) if owner else '')),
        ('Platform', sys.platform),
        ('Free RAM', str(free) + ' KB'),
        ('IP', _ip()),
    ]
    body = ['<h1>', _esc(title), '</h1><div class="card"><table>']
    for k, v in rows:
        body.append('<tr><td class="dim">' + k + '</td><td><code>' + _esc(str(v)) + '</code></td></tr>')
    body.append('</table></div>')
    links = '<a href="/api">JSON status</a>'
    if cfg.get('browse', 'true') == 'true':
        links = '<a href="/fs?path=/">&#128193; Browse files</a> &nbsp;&middot;&nbsp; ' + links
    body.append('<div class="card">' + links + '</div>')
    return ('<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">'
            '<title>' + _esc(title) + '</title><style>' + _CSS + '</style>' + ''.join(body))


def _browse(path):
    if not path:
        path = '/'
    try:
        names = sorted(uos.listdir(path))
    except OSError:
        return None   # 404
    up = path.rstrip('/')
    up = up[:up.rfind('/')] or '/' if '/' in up[1:] else '/'
    rows = ['<tr><td><a href="/fs?path=' + _esc(up) + '">&#11014; ..</a></td><td></td></tr>']
    for n in names:
        full = (path.rstrip('/') + '/' + n)
        if _is_dir(full):
            rows.append('<tr><td><a href="/fs?path=' + _esc(full) + '">&#128193; '
                        + _esc(n) + '/</a></td><td class="dim">dir</td></tr>')
        elif _is_secret(full):
            rows.append('<tr><td>&#128274; ' + _esc(n)
                        + '</td><td class="dim">protected</td></tr>')
        else:
            try:
                sz = uos.stat(full)[6]
            except OSError:
                sz = 0
            rows.append('<tr><td><a href="/dl?path=' + _esc(full) + '">&#128196; '
                        + _esc(n) + '</a></td><td class="dim">' + str(sz) + ' B</td></tr>')
    return ('<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">'
            '<title>' + _esc(path) + '</title><style>' + _CSS + '</style>'
            '<h1>&#128193; ' + _esc(path) + '</h1><div class="card"><table>'
            + ''.join(rows) + '</table></div><div class="card"><a href="/">&#8962; Home</a></div>')


def _api():
    import gc
    gc.collect()
    try:
        import regedit
        ver = regedit.read('Settings.Version') or '?'
        dev = regedit.read('System.Device_ID') or 'pulsar'
    except Exception:
        ver = dev = '?'
    return ('{"os":"RPCortex","version":"' + ver + '","device":"' + dev +
            '","platform":"' + sys.platform + '","free_kb":' + str(gc.mem_free() // 1024) +
            ',"ip":"' + _ip() + '"}')


# -- request handling ------------------------------------------------------

def _wr(conn, data):
    """Send ALL bytes — socket.send() may do partial sends on MicroPython."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    try:
        conn.sendall(data)
        return
    except AttributeError:
        pass
    except OSError:
        return
    mv = memoryview(data)
    while mv:
        try:
            n = conn.send(mv)
        except OSError:
            return
        if not n:
            return
        mv = mv[n:]


def _send(conn, status, ctype, body):
    if isinstance(body, str):
        body = body.encode('utf-8')
    hdr = ('HTTP/1.0 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n'
           'Connection: close\r\n\r\n').format(status, ctype, len(body))
    _wr(conn, hdr.encode('utf-8'))
    _wr(conn, body)
    try:
        return int(status.split(' ', 1)[0])
    except (ValueError, IndexError):
        return 0


def _stream(conn, path, ctype, download):
    """Stream a file to the client in 512-byte chunks. Returns status code."""
    try:
        sz = uos.stat(path)[6]
        f = open(path, 'rb')
    except OSError:
        return _send(conn, '404 Not Found', 'text/plain', 'Not found')
    name = path.rsplit('/', 1)[-1]
    disp = ('Content-Disposition: attachment; filename="{}"\r\n'.format(name)
            if download else '')
    hdr = ('HTTP/1.0 200 OK\r\nContent-Type: {}\r\n{}'
           'Content-Length: {}\r\nConnection: close\r\n\r\n').format(ctype, disp, sz)
    try:
        _wr(conn, hdr.encode('utf-8'))
        while True:
            chunk = f.read(512)
            if not chunk:
                break
            _wr(conn, chunk)
    finally:
        f.close()
    return 200


def _ctype(path):
    ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
    return _CTYPES.get(ext, 'application/octet-stream')


def _send_static(conn, serve_dir, urlpath):
    """Serve a file from serve_dir (static-site mode). '/' -> index.html."""
    rel = urlpath.lstrip('/')
    if '..' in rel.split('/'):                       # block path traversal
        return _send(conn, '403 Forbidden', 'text/plain', 'Forbidden')
    full = serve_dir.rstrip('/') + ('/' + rel if rel else '')
    if _is_dir(full):
        full = full.rstrip('/') + '/index.html'
    if _is_secret(full):
        return _send(conn, '403 Forbidden', 'text/plain', 'Forbidden')
    return _stream(conn, full, _ctype(full), False)


def _handle(conn, cfg):
    method = '?'; path = '-'; st = 0
    try:
        conn.settimeout(2.0)
        req = conn.recv(1024)
        if not req:
            return
        line = req.split(b'\r\n', 1)[0].decode('utf-8')
        parts = line.split(' ')
        method = parts[0] if parts else '?'
        if len(parts) < 2 or parts[0] != 'GET':
            st = _send(conn, '405 Method Not Allowed', 'text/plain', 'GET only')
            return
        path, q = _qs(parts[1])
        serve_dir = cfg.get('serve_dir', '')
        browse = cfg.get('browse', 'true') == 'true'
        if path == '/api':
            st = _send(conn, '200 OK', 'application/json', _api())
        elif path == '/fs':
            if not browse:
                st = _send(conn, '403 Forbidden', 'text/plain', 'File browsing is disabled')
            else:
                html = _browse(q.get('path', '/'))
                if html is None:
                    st = _send(conn, '404 Not Found', 'text/plain', 'No such folder')
                else:
                    st = _send(conn, '200 OK', 'text/html', html)
        elif path == '/dl':
            dlpath = q.get('path', '')
            if not browse:
                st = _send(conn, '403 Forbidden', 'text/plain', 'Downloads are disabled')
            elif _is_secret(dlpath):
                st = _send(conn, '403 Forbidden', 'text/plain', 'This file is protected')
            else:
                st = _stream(conn, dlpath, 'application/octet-stream', True)
        elif serve_dir:
            st = _send_static(conn, serve_dir, path)       # static-site mode
        elif path == '/':
            st = _send(conn, '200 OK', 'text/html', _dashboard(cfg))
        else:
            st = _send(conn, '404 Not Found', 'text/plain', 'Not found')
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
        _log(method, path, st)


# -- async request handling (background service only) ----------------------
# The sync _handle/_send/_stream above stay as the foreground server. The
# BACKGROUND server (_serve_async) uses these instead so a big file / slow client
# streams through an asyncio Stream and YIELDS to the event loop between chunks,
# instead of blocking it (which froze the foreground app + other services during a
# download). Single-connection (no task-per-client) to stay RAM-safe on RP2040.

async def _awr(stream, data):
    """Async send-all via an asyncio Stream; await drain() yields on backpressure."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    stream.write(data)
    await stream.drain()


async def _asend(stream, status, ctype, body):
    if isinstance(body, str):
        body = body.encode('utf-8')
    hdr = ('HTTP/1.0 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n'
           'Connection: close\r\n\r\n').format(status, ctype, len(body))
    await _awr(stream, hdr.encode('utf-8'))
    await _awr(stream, body)
    try:
        return int(status.split(' ', 1)[0])
    except (ValueError, IndexError):
        return 0


async def _astream(stream, path, ctype, download):
    """Stream a file to the client in 512-byte chunks, awaiting drain() between each
    so the event loop keeps running during a large transfer. Returns status code."""
    try:
        sz = uos.stat(path)[6]
        f = open(path, 'rb')
    except OSError:
        return await _asend(stream, '404 Not Found', 'text/plain', 'Not found')
    name = path.rsplit('/', 1)[-1]
    disp = ('Content-Disposition: attachment; filename="{}"\r\n'.format(name)
            if download else '')
    hdr = ('HTTP/1.0 200 OK\r\nContent-Type: {}\r\n{}'
           'Content-Length: {}\r\nConnection: close\r\n\r\n').format(ctype, disp, sz)
    try:
        await _awr(stream, hdr.encode('utf-8'))
        while True:
            chunk = f.read(512)
            if not chunk:
                break
            await _awr(stream, chunk)
    finally:
        f.close()
    return 200


async def _asend_static(stream, serve_dir, urlpath):
    rel = urlpath.lstrip('/')
    if '..' in rel.split('/'):
        return await _asend(stream, '403 Forbidden', 'text/plain', 'Forbidden')
    full = serve_dir.rstrip('/') + ('/' + rel if rel else '')
    if _is_dir(full):
        full = full.rstrip('/') + '/index.html'
    if _is_secret(full):
        return await _asend(stream, '403 Forbidden', 'text/plain', 'Forbidden')
    return await _astream(stream, full, _ctype(full), False)


async def _handle_async(conn, cfg):
    """Async per-connection handler for the background server. Wraps the accepted
    socket in an asyncio Stream so recv + every send/stream yields to the loop. Same
    routing as the sync _handle. Never raises out (logs + closes in finally)."""
    import asyncio
    method = '?'; path = '-'; st = 0
    try:
        conn.setblocking(False)
    except Exception:
        pass
    try:
        stream = asyncio.StreamReader(conn)     # Stream: read + write + drain
    except Exception:
        # Couldn't wrap (unexpected) — fall back to the sync handler so the request
        # is still served (it just won't yield during this one transfer).
        _handle(conn, cfg)
        return
    try:
        try:
            req = await asyncio.wait_for(stream.read(1024), 5)
        except Exception:
            req = b''
        if not req:
            return
        line = req.split(b'\r\n', 1)[0].decode('utf-8')
        parts = line.split(' ')
        method = parts[0] if parts else '?'
        if len(parts) < 2 or parts[0] != 'GET':
            st = await _asend(stream, '405 Method Not Allowed', 'text/plain', 'GET only')
            return
        path, q = _qs(parts[1])
        serve_dir = cfg.get('serve_dir', '')
        browse = cfg.get('browse', 'true') == 'true'
        if path == '/api':
            st = await _asend(stream, '200 OK', 'application/json', _api())
        elif path == '/fs':
            if not browse:
                st = await _asend(stream, '403 Forbidden', 'text/plain', 'File browsing is disabled')
            else:
                html = _browse(q.get('path', '/'))
                if html is None:
                    st = await _asend(stream, '404 Not Found', 'text/plain', 'No such folder')
                else:
                    st = await _asend(stream, '200 OK', 'text/html', html)
        elif path == '/dl':
            dlpath = q.get('path', '')
            if not browse:
                st = await _asend(stream, '403 Forbidden', 'text/plain', 'Downloads are disabled')
            elif _is_secret(dlpath):
                st = await _asend(stream, '403 Forbidden', 'text/plain', 'This file is protected')
            else:
                st = await _astream(stream, dlpath, 'application/octet-stream', True)
        elif serve_dir:
            st = await _asend_static(stream, serve_dir, path)
        elif path == '/':
            st = await _asend(stream, '200 OK', 'text/html', _dashboard(cfg))
        else:
            st = await _asend(stream, '404 Not Found', 'text/plain', 'Not found')
    except Exception:
        pass
    finally:
        try:
            await stream.wait_closed()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
        _log(method, path, st)


def _serve(port, cfg):
    """Foreground accept loop. Polls stdin for q/Ctrl+C SEPARATELY from the
    socket — mixing a lwip socket and USB-CDC stdin in one select() is
    unreliable on the rp2 port (it was the 'really weird, never works' bug).
    Instead: a short accept() timeout drives the loop; stdin is polled with a
    zero-timeout select between accepts (the proven SysMon pattern)."""
    import socket
    import select
    if not _online():
        return
    ip = _ip()
    try:
        addr = socket.getaddrinfo('0.0.0.0', port)[0][-1]
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(addr)
        srv.listen(2)
        srv.settimeout(0.4)
    except Exception as e:
        error("Could not start server on port {}: {}".format(port, e))
        return
    ok("Serving on  http://{}:{}/   (press q or Ctrl+C to stop)".format(ip, port))
    if cfg.get('serve_dir'):
        info("Static site from: {}   (browse: {})".format(cfg['serve_dir'], cfg.get('browse')))
    else:
        info("Routes: /  /api" + ("  /fs?path=/  /dl?path=<file>"
             if cfg.get('browse') == 'true' else "  (file browser off)"))
    try:
        while True:
            # poll the keyboard without blocking
            try:
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    c = sys.stdin.read(1)
                    if c in ('q', 'Q', '\x03'):
                        break
            except (OSError, ValueError):
                pass
            # accept the next connection (blocks up to the socket timeout)
            try:
                conn, client = srv.accept()
            except OSError:
                continue   # timeout — loop back and re-poll the keyboard
            _handle(conn, cfg)
    finally:
        try:
            srv.close()
        except Exception:
            pass
        multi("")
        ok("httpd stopped.  ({} request(s) logged)".format(len(_LOG)))


# -- background service (async, Track B / v0.9.5) --------------------------
# Run the server as a supervised coroutine in the async shell so it serves WHILE
# you keep using the prompt.  This coro NEVER writes to stdout (only the in-RAM
# ring buffer + _BG stats) so it can't corrupt the shell line.  It wraps a
# NON-BLOCKING accept(): on EAGAIN it yields to the event loop, keeping the shell
# responsive.  The launchpad service manager (re)spawns it from a factory.
#
# Surviving Ctrl+C: if an event loop is discarded (Ctrl+C tore it down), the old
# _serve_async coroutine is orphaned with its listening socket still OPEN — and a
# still-LISTENING socket blocks a rebind even with SO_REUSEADDR (that was the
# 'EADDRINUSE on Ctrl+C' bug).  So we stash the socket in _BG['sock'] and CLOSE
# any previous one before binding.  Closing a LISTEN socket on lwip is immediate
# (no TIME_WAIT), so the respawn always rebinds cleanly and no PCB leaks.

_BG = {'running': False, 'port': 0, 'started': 0, 'requests': 0, 'errors': 0,
       'sock': None}


def _lp():
    """The live launchpad module — the service manager lives there."""
    try:
        return sys.modules['Core.launchpad']
    except Exception:
        return None


def _uptime_str():
    if not _BG['started']:
        return '-'
    try:
        import utime
        secs = utime.ticks_diff(utime.ticks_ms(), _BG['started']) // 1000
    except Exception:
        return '-'
    if secs < 0:
        secs = 0
    h = secs // 3600; m = (secs % 3600) // 60; s = secs % 60
    if h:
        return '{}h {}m {}s'.format(h, m, s)
    if m:
        return '{}m {}s'.format(m, s)
    return '{}s'.format(s)


async def _serve_async(port, cfg):
    """Background accept loop for the service manager (see note above)."""
    import asyncio
    import socket
    # Close any socket a previous instance left bound (e.g. an orphaned coro from
    # a Ctrl+C-discarded loop) BEFORE binding — a still-LISTENING socket would
    # otherwise EADDRINUSE the rebind, SO_REUSEADDR notwithstanding.
    old = _BG.get('sock')
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
        _BG['sock'] = None
    srv = None
    try:
        addr = socket.getaddrinfo('0.0.0.0', port)[0][-1]
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(addr)
        srv.listen(2)
        srv.setblocking(False)
        _BG['sock'] = srv
    except Exception:
        _BG['running'] = False
        if srv is not None:
            try:
                srv.close()
            except Exception:
                pass
        raise
    _BG['running'] = True
    _BG['port'] = port
    _BG['requests'] = 0
    _BG['errors'] = 0
    try:
        import utime
        _BG['started'] = utime.ticks_ms()
    except Exception:
        _BG['started'] = 0
    _log('---', 'background server up on :{}'.format(port), 0)
    try:
        while True:
            try:
                conn, client = srv.accept()
            except OSError:
                await asyncio.sleep_ms(60)     # EAGAIN: nothing pending — yield
                continue
            try:
                await _handle_async(conn, cfg)  # async: streams + yields during the
                _BG['requests'] += 1            # transfer instead of blocking the loop
            except Exception:
                _BG['errors'] += 1
            await asyncio.sleep_ms(0)          # let other coros run between hits
    finally:
        _BG['running'] = False
        try:
            srv.close()
        except Exception:
            pass
        if _BG.get('sock') is srv:        # only clear if it's still ours
            _BG['sock'] = None
        _log('---', 'background server stopped', 0)


def _start_bg(cfg):
    """Register httpd as a background service in the async shell."""
    lp = _lp()
    if lp is None or not hasattr(lp, 'register_service'):
        error("Background services need the async shell. Enable it: asyncmode on")
        return
    if not _online():
        return
    port = cfg['port']

    def _factory():
        # Fresh coroutine + fresh cfg each (re)spawn, on the chosen port.
        return _serve_async(port, _load_cfg())

    lp.register_service('httpd', _factory)
    if getattr(lp, '_async_active', False):
        ok("httpd is serving in the background on port {}.".format(port))
        if _ip() != '0.0.0.0':
            info("  ->  http://{}:{}/".format(_ip(), port))
        info("Check it: 'httpd status'.  Stop it: 'httpd stop'.")
    else:
        ok("httpd registered as a background service (port {}).".format(port))
        info("It starts when the async shell opens. Enable it: asyncmode on")


def _stop_bg():
    lp = _lp()
    if lp is None or not hasattr(lp, 'unregister_service'):
        warn("No background service manager available (async shell only).")
        return
    if lp.unregister_service('httpd'):
        _BG['running'] = False
        ok("httpd background service stopped.")
    else:
        info("httpd wasn't running in the background.")


# -- control panel (TUI) ---------------------------------------------------

_sel = 's'
_NAV = ['s', 'p', 't', 'd', 'b', 'l', 'c']


def _free_kb():
    try:
        import gc
        gc.collect()
        return gc.mem_free() // 1024
    except Exception:
        return 0


def _sec(title):
    prefix = '== {} '.format(title)
    return _CY + prefix + _DG + '=' * max(0, _W - len(prefix)) + _R


def _lead(key):
    return (_CY + _BD + '> ' + _R) if key == _sel else '  '


def _row(key, label, value, vcol=None, note=''):
    vcol = vcol or _YL
    ntxt = ('   ' + _DG + note + _R) if note else ''
    return (_lead(key) + _WH + '[' + key + ']' + _R + ' ' +
            '{:<18}'.format(label) + ' : ' + vcol + value + _R + ntxt)


# In-place redraw engine (mirrors Core settings.py): the panel is painted once,
# then navigation rewrites ONLY the affected row via relative cursor moves —
# no full-screen clear per keystroke, so it doesn't flicker at 115200 baud.
_idx = {}        # row key -> line index within the drawn panel
_nlines = 0      # total content lines (the prompt sits on line _nlines)
_PROMPT = 'Choice: '


def _row_for(key, cfg):
    """Build one panel row from the current config."""
    if key == 's':
        ip = _ip()
        url = ('http://{}:{}/'.format(ip, cfg['port']) if ip != '0.0.0.0'
               else '(connect WiFi first)')
        return _row('s', 'Start server', url, _GR)
    if key == 'p':
        return _row('p', 'Port', str(cfg['port']))
    if key == 't':
        return _row('t', 'Title', cfg.get('title') or '(device name)',
                    _YL if cfg.get('title') else _DG)
    if key == 'd':
        return _row('d', 'Serve directory', cfg.get('serve_dir') or '(built-in dashboard)',
                    _YL if cfg.get('serve_dir') else _DG)
    if key == 'b':
        on = cfg.get('browse', 'true') == 'true'
        return _row('b', 'Browse files', 'ON' if on else 'OFF', _GR if on else _DG,
                    'filesystem exposed read-only' if on else 'dashboard / site only')
    if key == 'l':
        return _row('l', 'View request log', '{} request(s)'.format(len(_LOG)))
    if key == 'c':
        return _row('c', 'Clear log', '', _DG)
    return ''


def _build_lines(cfg):
    lines = []
    idx = {}
    left = 'RPCortex Web Server'
    right = '{} KB free   {}'.format(_free_kb(), _ip())
    pad = max(1, _W - 2 - len(left) - len(right))
    lines.append('  ' + _WH + _BD + left + _R + ' ' * pad + _DG + right + _R)
    lines.append(_DG + '=' * _W + _R)
    lines.append('')
    lines.append(_sec('SERVER'))
    idx['s'] = len(lines); lines.append(_row_for('s', cfg))
    lines.append('')
    lines.append(_sec('CONFIG'))
    idx['p'] = len(lines); lines.append(_row_for('p', cfg))
    idx['t'] = len(lines); lines.append(_row_for('t', cfg))
    idx['d'] = len(lines); lines.append(_row_for('d', cfg))
    idx['b'] = len(lines); lines.append(_row_for('b', cfg))
    lines.append('')
    lines.append(_sec('LOGS'))
    idx['l'] = len(lines); lines.append(_row_for('l', cfg))
    idx['c'] = len(lines); lines.append(_row_for('c', cfg))
    lines.append('')
    lines.append(_DG + '=' * _W + _R)
    lines.append('  ' + _DG + 'Up/Down' + _R + ' move   ' + _DG + 'Enter' + _R +
                 ' select   ' + _DG + 'letter' + _R + ' jump   ' + _DG + '[r]' + _R +
                 ' refresh   ' + _DG + '[q]' + _R + ' quit')
    return lines, idx


def _full_draw(cfg):
    global _idx, _nlines
    lines, _idx = _build_lines(cfg)
    _nlines = len(lines)
    out = ['\x1b[2J\x1b[H\x1b[?25h']
    for ln in lines:
        out.append(ln); out.append('\r\n')
    out.append(_PROMPT)
    sys.stdout.write(''.join(out))


def _update(key, cfg):
    """Rewrite just one row in place, then return the cursor to the prompt."""
    i = _idx.get(key)
    if i is None:
        return
    up = _nlines - i
    sys.stdout.write('\x1b[{}A\r'.format(up))
    sys.stdout.write(_row_for(key, cfg) + '\x1b[K')
    sys.stdout.write('\x1b[{}B\r'.format(up))
    sys.stdout.write(_PROMPT)


def _view_log():
    sys.stdout.write('\x1b[2J\x1b[H')
    info('Request log  ({} entr{})'.format(len(_LOG), 'y' if len(_LOG) == 1 else 'ies'))
    multi('  ' + _DG + 'time      method code path' + _R)
    if not _LOG:
        multi('  (no requests yet — start the server and hit it from a browser)')
    else:
        for entry in _LOG:
            multi('  ' + entry)
    multi('')
    info('Press any key to return.')
    try:
        sys.stdin.read(1)
    except Exception:
        pass


def _edit(cfg, key):
    """Edit a config value, save httpd.cfg, return True if it changed."""
    sys.stdout.write('\x1b[2J\x1b[H')
    if key == 'p':
        info('Edit listen port')
        multi('  Current: {}'.format(cfg['port']))
        val = inpt('New port (blank = keep)').strip()
        if not val:
            return False
        if not val.isdigit() or not (1 <= int(val) <= 65535):
            warn('Port must be a number 1-65535.')
            sys.stdin.read(1)
            return False
        cfg['port'] = int(val)
    elif key == 't':
        info('Edit dashboard title')
        multi('  Current: {}'.format(cfg.get('title') or '(device name)'))
        multi("  Enter '-' to clear it back to the device name.")
        val = inpt('New title (blank = keep)').strip()
        if not val:
            return False
        cfg['title'] = '' if val == '-' else val
    elif key == 'd':
        info('Edit serve directory (static-site mode)')
        multi('  Current: {}'.format(cfg.get('serve_dir') or '(built-in dashboard)'))
        multi("  A folder with an index.html, e.g. /Users/root/site")
        multi("  Enter '-' to clear it (back to the built-in dashboard).")
        val = inpt('New serve_dir (blank = keep)').strip()
        if not val:
            return False
        if val == '-':
            cfg['serve_dir'] = ''
        elif not _is_dir(val):
            warn("'{}' is not a folder on this device.".format(val))
            sys.stdin.read(1)
            return False
        else:
            cfg['serve_dir'] = val
    else:
        return False
    if not _save_cfg(cfg):
        warn('Could not write httpd.cfg (read-only?).')
        sys.stdin.read(1)
    return True


def _panel_loop(cfg):
    """Interactive control panel. Returns when the user quits."""
    global _sel
    _full_draw(cfg)
    while True:
        try:
            ch = sys.stdin.read(1)
        except Exception:
            break

        if ch == '\x1b':                      # arrow keys / bare ESC quits
            try:
                if sys.stdin.read(1) == '[':
                    a = sys.stdin.read(1)
                    if a in ('A', 'B'):
                        old = _sel
                        i = _NAV.index(_sel) if _sel in _NAV else 0
                        i = (i - 1) % len(_NAV) if a == 'A' else (i + 1) % len(_NAV)
                        _sel = _NAV[i]
                        _update(old, cfg)     # un-highlight old row
                        _update(_sel, cfg)    # highlight new row
                else:
                    break
            except Exception:
                pass
            continue

        if ch in ('q', 'Q', '\x03'):
            break

        act = _sel if ch in ('\r', '\n') else ch.lower()
        if act not in _NAV:
            if ch in ('r', 'R'):
                _full_draw(cfg)
            continue
        old = _sel
        _sel = act
        if old != _sel:
            _update(old, cfg)                 # move highlight to the chosen row

        if act == 's':
            sys.stdout.write('\x1b[2J\x1b[H')
            _serve(cfg['port'], cfg)          # blocks until q/Ctrl+C (which it consumes)
            info('Press any key to return to the panel.')
            try:
                sys.stdin.read(1)
            except Exception:
                pass
            _full_draw(cfg)
        elif act == 'b':
            cfg['browse'] = 'false' if cfg.get('browse', 'true') == 'true' else 'true'
            _save_cfg(cfg)
            _update('b', cfg)
        elif act in ('p', 't', 'd'):
            _edit(cfg, act)
            _full_draw(cfg)
        elif act == 'l':
            _view_log()
            _full_draw(cfg)
        elif act == 'c':
            del _LOG[:]
            _update('l', cfg)                 # the log-count row reflects the clear
            _update('c', cfg)

    sys.stdout.write('\x1b[2J\x1b[H')
    ok("httpd panel closed.")


# -- status (text) ---------------------------------------------------------

def _status(cfg):
    lp = _lp()
    live = False
    if lp is not None and hasattr(lp, 'service_running'):
        try:
            live = lp.service_running('httpd')
        except Exception:
            live = False
    live = live or _BG['running']
    if live:
        port = _BG['port'] or cfg['port']
        ok("httpd: RUNNING in the background")
        multi("  Port      : {}".format(port))
        multi("  Uptime    : {}".format(_uptime_str()))
        multi("  Requests  : {}   (errors: {})".format(_BG['requests'], _BG['errors']))
        if _ip() != '0.0.0.0':
            multi("  URL       : http://{}:{}/".format(_ip(), port))
        multi("  Stop with : httpd stop")
    else:
        info("httpd: not running in the background.")
        multi("  Background: httpd start --bg   (needs 'asyncmode on')")
        multi("  Foreground: httpd start [port] (blocks until q / Ctrl+C)")
    multi("  Config: port={}  title='{}'  browse={}  serve_dir='{}'".format(
        cfg['port'], cfg.get('title', ''), cfg.get('browse'), cfg.get('serve_dir', '')))
    if cfg.get('serve_dir'):
        multi("  Hosting the static site in '{}' (put your index.html there).".format(cfg['serve_dir']))
    else:
        multi("  Serving the built-in dashboard + file browser.")
    if _ip() == '0.0.0.0':
        multi("  Connect to WiFi first:  wifi connect")


# -- entry point -----------------------------------------------------------

def httpd(args=None):
    """Tiny web server: dashboard / static site + file browser over WiFi.
    Run 'httpd' for the control panel; 'httpd start [port]' to serve directly;
    'httpd start --bg' to run it in the background (async shell); 'httpd status'
    / 'httpd stop' to check or stop the background server."""
    cfg = _load_cfg()
    a = (args or '').strip().split()
    sub = a[0].lower().lstrip('-') if a else ''   # accept 'status' or '--status'
    if sub in ('help', 'h', '?'):
        info("httpd - a tiny web server (dashboard / static site / file browser)")
        multi("  httpd                 open the control panel (config, logs, start)")
        multi("  httpd start [port]    serve in the FOREGROUND (q / Ctrl+C to stop)")
        multi("  httpd start --bg      serve in the BACKGROUND (needs 'asyncmode on')")
        multi("  httpd status          show the background server's stats")
        multi("  httpd stop            stop the background server")
        multi("  Auto-start at login:  service add \"httpd start --bg\"")
        multi("  Config lives in {}/httpd.cfg and is editable in the panel.".format(_pkg_dir()))
        return
    if not a or sub in ('panel', 'config', 'cfg', 'tui'):
        _panel_loop(cfg)
    elif sub == 'status':
        _status(cfg)
    elif sub == 'stop':
        _stop_bg()
    elif sub == 'start':
        bg = False
        for x in a[1:]:
            xl = x.lower()
            if xl in ('--bg', '-b', 'bg', 'background'):
                bg = True
            elif x.isdigit():
                cfg['port'] = int(x)
            else:
                warn("Ignoring unknown argument '{}'.".format(x))
        if bg:
            _start_bg(cfg)
        else:
            _serve(cfg['port'], cfg)
    else:
        warn("Usage: httpd [start [port] [--bg] | status | stop | help]")


if __name__ == '__main__':
    httpd()
