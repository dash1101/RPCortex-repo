# Desc: httpd - a tiny web server for RPCortex - Pulsar OS
# File: /Packages/HTTPd/httpd.py
# Version: 0.1.0
# Author: dash1101
#
# Serve a live status dashboard + a browsable/downloadable view of the device
# filesystem over WiFi. A foreground server (RPCortex is single-threaded until
# the v0.9.5 uasyncio work), so it runs until you press q or Ctrl+C.
#
# Shell command:
#   httpd                 show status + your URL
#   httpd start [port]    start the server (default port 8080)
#
# Routes:  /  (dashboard)   /api (JSON status)   /fs?path=/  (file browser)
#          /dl?path=<file>  (download a file)
#
# SECURITY: this exposes the whole filesystem read-only to anyone on the
# network. Run it only on a trusted LAN; stop it (q) when you're done.
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.

import sys
import uos

from RPCortex import ok, info, warn, error, multi

_DIR_FLAG = 0x4000
_DEFAULT_PORT = 8080


# -- helpers ---------------------------------------------------------------

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


def _dashboard():
    import gc
    try:
        import regedit
        ver = regedit.read('Settings.Version') or '?'
        dev = regedit.read('System.Device_ID') or 'pulsar'
        owner = regedit.read('System.Owner') or ''
        build = regedit.read('System.Build') or 'source'
    except Exception:
        ver = dev = build = '?'; owner = ''
    gc.collect()
    free = gc.mem_free() // 1024
    rows = [
        ('OS', 'RPCortex ' + ver + '  (build ' + build + ')'),
        ('Device', dev + (('  -  ' + owner) if owner else '')),
        ('Platform', sys.platform),
        ('Free RAM', str(free) + ' KB'),
        ('IP', _ip()),
    ]
    body = ['<h1>RPCortex &mdash; ', _esc(dev), '</h1><div class="card"><table>']
    for k, v in rows:
        body.append('<tr><td class="dim">' + k + '</td><td><code>' + _esc(str(v)) + '</code></td></tr>')
    body.append('</table></div>')
    body.append('<div class="card"><a href="/fs?path=/">&#128193; Browse files</a>'
                ' &nbsp;&middot;&nbsp; <a href="/api">JSON status</a></div>')
    return ('<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">'
            '<title>RPCortex</title><style>' + _CSS + '</style>' + ''.join(body))


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

def _send(conn, status, ctype, body):
    if isinstance(body, str):
        body = body.encode('utf-8')
    hdr = ('HTTP/1.0 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n'
           'Connection: close\r\n\r\n').format(status, ctype, len(body))
    conn.send(hdr.encode('utf-8'))
    conn.send(body)


def _send_file(conn, path):
    try:
        sz = uos.stat(path)[6]
        f = open(path, 'rb')
    except OSError:
        _send(conn, '404 Not Found', 'text/plain', 'Not found')
        return
    name = path.rsplit('/', 1)[-1]
    hdr = ('HTTP/1.0 200 OK\r\nContent-Type: application/octet-stream\r\n'
           'Content-Disposition: attachment; filename="{}"\r\n'
           'Content-Length: {}\r\nConnection: close\r\n\r\n').format(name, sz)
    try:
        conn.send(hdr.encode('utf-8'))
        while True:
            chunk = f.read(512)
            if not chunk:
                break
            conn.send(chunk)
    except Exception:
        pass
    finally:
        f.close()


def _handle(conn):
    try:
        conn.settimeout(2.0)
        req = conn.recv(1024)
        if not req:
            return
        line = req.split(b'\r\n', 1)[0].decode('utf-8')
        parts = line.split(' ')
        if len(parts) < 2 or parts[0] != 'GET':
            _send(conn, '405 Method Not Allowed', 'text/plain', 'GET only')
            return
        path, q = _qs(parts[1])
        if path == '/':
            _send(conn, '200 OK', 'text/html', _dashboard())
        elif path == '/api':
            _send(conn, '200 OK', 'application/json', _api())
        elif path == '/fs':
            html = _browse(q.get('path', '/'))
            if html is None:
                _send(conn, '404 Not Found', 'text/plain', 'No such folder')
            else:
                _send(conn, '200 OK', 'text/html', html)
        elif path == '/dl':
            _send_file(conn, q.get('path', ''))
        else:
            _send(conn, '404 Not Found', 'text/plain', 'Not found')
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _serve(port):
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
    except Exception as e:
        error("Could not start server on port {}: {}".format(port, e))
        return
    ok("Serving on  http://{}:{}/   (press q or Ctrl+C to stop)".format(ip, port))
    info("Routes: /  /api  /fs?path=/  /dl?path=<file>")
    try:
        while True:
            r, _, _ = select.select([srv, sys.stdin], [], [], 0.4)
            if sys.stdin in r:
                c = sys.stdin.read(1)
                if c in ('q', 'Q', '\x03'):
                    break
            if srv in r:
                try:
                    conn, client = srv.accept()
                except OSError:
                    continue
                _handle(conn)
    finally:
        try:
            srv.close()
        except Exception:
            pass
        multi("")
        ok("httpd stopped.")


def httpd(args=None):
    """Tiny web server: dashboard + file browser over WiFi."""
    a = (args or '').strip().split()
    if not a:
        info("httpd — a tiny web server (dashboard + file browser)")
        multi("  httpd start [port]   start serving (default {})".format(_DEFAULT_PORT))
        if _ip() != '0.0.0.0':
            multi("  Your IP: {}  ->  it'll be at http://{}:{}/".format(_ip(), _ip(), _DEFAULT_PORT))
        else:
            multi("  Connect to WiFi first:  wifi connect")
        return
    if a[0] == 'start':
        port = _DEFAULT_PORT
        if len(a) > 1:
            try:
                port = int(a[1])
            except ValueError:
                warn("Invalid port '{}'.".format(a[1]))
                return
        _serve(port)
    else:
        warn("Usage: httpd start [port]")


if __name__ == '__main__':
    httpd('start')
