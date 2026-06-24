# Desc: Nova D1 web control panel — drive the device from a phone over WiFi.
# File: /Packages/NovaD1/novaweb.py
#
# A small async web server (background service, started when WiFi is up) serving a
# mobile page: device status, one-tap app buttons, and a shell box that runs a
# command on the device and returns its output. Modeled on the httpd package's
# async server (close-before-bind, non-blocking accept, StreamReader + drain per
# chunk) so it shares one event loop with the GUI + serial shell without blocking.
#
# SECURITY: this runs shell commands. It's meant for the OWNER on their OWN LAN.
# Set Apps.NovaD1_Web_PIN to require a PIN; empty = open (LAN-only, seamless).
# Commands run synchronously (the OS shell is sync), so a long command briefly
# pauses the screen — fine for status/quick commands.
# MicroPython-safe: no f-strings, positional split, .format() only.

import sys

_BG = {'sock': None, 'running': False, 'requests': 0, 'port': 0}


def _reg(key, default=None):
    try:
        import regedit
        v = regedit.read(key)
        return v if v not in (None, '') else default
    except Exception:
        return default


def _online():
    try:
        import network
        return network.WLAN(network.STA_IF).isconnected()
    except Exception:
        return False


def _ip():
    try:
        import network
        return network.WLAN(network.STA_IF).ifconfig()[0]
    except Exception:
        return '0.0.0.0'


def _urldecode(s):
    s = s.replace('+', ' ')
    out = ''
    i = 0
    while i < len(s):
        if s[i] == '%' and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except Exception:
                pass
        out += s[i]
        i += 1
    return out


def _qs(target):
    if '?' not in target:
        return target, {}
    path, q = target.split('?', 1)
    out = {}
    for kv in q.split('&'):
        if '=' in kv:
            k, v = kv.split('=', 1)
            out[_urldecode(k)] = _urldecode(v)
    return path, out


def _status_json():
    import gc
    try:
        import RPCortex
        ver = RPCortex.OS_VERSION
    except Exception:
        ver = '?'
    return ('{"ip":"%s","version":"%s","free":%d,"wifi":%s}'
            % (_ip(), ver, gc.mem_free(), 'true' if _online() else 'false'))


def _strip_ansi(s):
    out = ''
    i = 0
    n = len(s)
    while i < n:
        if s[i] == '\x1b':
            j = i + 1
            while j < n and not ('a' <= s[j] <= 'z' or 'A' <= s[j] <= 'Z'):
                j += 1
            i = j + 1
        else:
            out += s[i]
            i += 1
    return out


def _run_cmd(cmd):
    """Run a shell line on the device, return its full captured output (text).
    Redirects sys.stdout so info/ok/warn/multi/print are all captured (the OS
    multi-only capture would miss most of it)."""
    lp = sys.modules.get('Core.launchpad') or sys.modules.get('launchpad')
    if lp is None or not hasattr(lp, '_run_line'):
        return 'shell engine not found'
    out = ''
    try:
        import io
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            lp._run_line(cmd)
        finally:
            sys.stdout = old
        out = buf.getvalue()
    except Exception:
        try:
            import RPCortex
            RPCortex.begin_capture()
            try:
                lp._run_line(cmd)
            except Exception:
                pass
            out = RPCortex.end_capture() or ''
        except Exception:
            out = ''
    return _strip_ansi(out) or '(no output)'


_PAGE = """<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Nova D1</title><style>
*{box-sizing:border-box}body{margin:0;background:#0a0e1a;color:#cfe6ff;
font-family:-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:560px;margin:0 auto;padding:14px}
h1{font-size:20px;margin:6px 0;color:#7fd1ff;letter-spacing:1px}
.s{font-size:12px;color:#7790b0;margin-bottom:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0}
button{background:#13203a;color:#cfe6ff;border:1px solid #24406e;border-radius:10px;
padding:12px;font-size:15px}button:active{background:#1d3a6e}
.row{display:flex;gap:8px;margin:10px 0}input{flex:1;background:#0d1426;color:#cfe6ff;
border:1px solid #24406e;border-radius:10px;padding:12px;font-size:15px}
pre{background:#070b14;border:1px solid #1b2c4a;border-radius:10px;padding:10px;
font-size:13px;white-space:pre-wrap;word-break:break-word;min-height:60px;color:#aee0b0}
.b{background:#16325a}</style></head><body><div class=wrap>
<h1>NOVA D1</h1><div class=s id=st>connecting...</div>
<div class=grid>
<button onclick="r('sysinfo')">System</button>
<button onclick="r('meminfo')">Memory</button>
<button onclick="r('df')">Storage</button>
<button onclick="r('wifi status')">WiFi</button>
<button onclick="r('novad1 status')">Nova</button>
<button onclick="r('novad1 logs 20')">Logs</button>
</div>
<div class=row><input id=c placeholder="shell command, e.g. ls"
onkeydown="if(event.key=='Enter')run()"><button class=b onclick=run()>Run</button></div>
<pre id=o>Ready.</pre></div><script>
var P=localStorage.nvpin||'';
function st(){fetch('/status').then(r=>r.json()).then(j=>{
document.getElementById('st').textContent=j.ip+'  v'+j.version+'  '+(j.free/1024|0)+'KB free';})}
function out(t){document.getElementById('o').textContent=t}
function q(c){return '/cmd?c='+encodeURIComponent(c)+(P?'&pin='+encodeURIComponent(P):'')}
function r(c){out('...');fetch(q(c)).then(x=>{if(x.status==403){P=prompt('PIN:')||'';localStorage.nvpin=P;return r(c)}return x.text()}).then(out)}
function run(){var c=document.getElementById('c').value;if(c)r(c)}
st();setInterval(st,5000);
</script></body></html>"""


async def _awr(stream, data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    stream.write(data)
    await stream.drain()


async def _asend(stream, status, ctype, body):
    if isinstance(body, str):
        body = body.encode('utf-8')
    hdr = ('HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
           'Connection: close\r\n\r\n' % (status, ctype, len(body)))
    await _awr(stream, hdr)
    await _awr(stream, body)
    return status


async def _handle_async(conn):
    import asyncio
    try:
        conn.setblocking(False)
    except Exception:
        pass
    try:
        stream = asyncio.StreamReader(conn)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
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
        if len(parts) < 2:
            return
        path, q = _qs(parts[1])
        if path == '/status':
            await _asend(stream, '200 OK', 'application/json', _status_json())
        elif path == '/cmd':
            pin = _reg('Apps.NovaD1_Web_PIN', '')
            if pin and q.get('pin', '') != pin:
                await _asend(stream, '403 Forbidden', 'text/plain', 'PIN required')
            else:
                cmd = q.get('c', '').strip()
                _BG['requests'] += 1
                out = _run_cmd(cmd) if cmd else '(empty)'
                await _asend(stream, '200 OK', 'text/plain', out)
        elif path == '/' or path == '/index.html':
            await _asend(stream, '200 OK', 'text/html', _PAGE)
        else:
            await _asend(stream, '404 Not Found', 'text/plain', 'Not found')
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


async def serve():
    """Background service: wait for WiFi, bind, serve. Retries if WiFi drops."""
    import asyncio
    import socket
    try:
        port = int(_reg('Apps.NovaD1_Web_Port', 80))
    except (TypeError, ValueError):
        port = 80
    while True:
        if not _online():
            await asyncio.sleep_ms(3000)
            continue
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
            _BG['running'] = True
            _BG['port'] = port
        except Exception:
            if srv is not None:
                try:
                    srv.close()
                except Exception:
                    pass
            await asyncio.sleep_ms(5000)
            continue
        try:
            while _online():
                try:
                    conn, _client = srv.accept()
                except OSError:
                    await asyncio.sleep_ms(60)
                    continue
                try:
                    await _handle_async(conn)
                except Exception:
                    pass
                await asyncio.sleep_ms(0)
        except Exception:
            pass
        finally:
            _BG['running'] = False
            try:
                srv.close()
            except Exception:
                pass
            if _BG.get('sock') is srv:
                _BG['sock'] = None
        await asyncio.sleep_ms(2000)
