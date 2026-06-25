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


def _wifi_scan():
    """Scan for networks (JSON list). Pauses the background WiFi manager so it
    isn't mid-connect on the shared STA interface."""
    try:
        import novawifi
        novawifi.pause()
    except Exception:
        novawifi = None
    saved = set()
    try:
        import net
        saved = set(s.lower() for s, _p in net._read_networks())
    except Exception:
        pass
    out = []
    try:
        import network
        wlan = network.WLAN(network.STA_IF)
        if not wlan.active():
            wlan.active(True)
        seen = set()
        for r in (wlan.scan() or []):
            try:
                ssid = r[0].decode() if isinstance(r[0], (bytes, bytearray)) else str(r[0])
            except Exception:
                continue
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            rssi = r[3] if len(r) > 3 else 0
            out.append((ssid, rssi, ssid.lower() in saved))
    except Exception:
        pass
    finally:
        try:
            if novawifi:
                novawifi.resume()
        except Exception:
            pass
    out.sort(key=lambda x: x[1], reverse=True)
    parts = []
    for ssid, rssi, k in out[:25]:
        s = ssid.replace('"', "'")
        parts.append('{"s":"%s","r":%d,"k":%s}' % (s, rssi, 'true' if k else 'false'))
    return '[' + ','.join(parts) + ']'


def _codes_json():
    try:
        import novastore
        parts = []
        for cat in novastore.CATS:
            for n in novastore.list_codes(cat):
                parts.append('{"c":"%s","n":"%s"}' % (cat, n.replace('"', "'")))
        return '[' + ','.join(parts) + ']'
    except Exception:
        return '[]'


def _msg_json():
    try:
        import novamsg
        box = novamsg.inbox()
    except Exception:
        box = []
    parts = []
    for m in box[-25:]:
        who = 'me' if m.get('me') else str(m.get('src', '?'))
        t = str(m.get('text', '')).replace('\\', '').replace('"', "'")
        parts.append('{"w":"%s","t":"%s"}' % (who, t))
    return '[' + ','.join(parts) + ']'


def _wifi_join(ssid, pw):
    """Save the network; the background manager then connects to it (no blocking,
    no fighting the manager). Returns a status string."""
    if not ssid:
        return 'no SSID'
    _run_cmd('wifi add "{}" "{}"'.format(ssid, pw))
    return 'Saved "{}" - connecting in background.'.format(ssid)


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
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#070b16;color:#dbe8ff;font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:600px;margin:0 auto;padding:14px}
.hd{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.hd .bk{font-size:24px;color:#7fd1ff;display:none;width:18px}
.hd b{font-size:20px;letter-spacing:2px;background:linear-gradient(90deg,#7fd1ff,#a98bff);-webkit-background-clip:text;background-clip:text;color:transparent}
.hd .s{margin-left:auto;font-size:12px;color:#8aa0c4}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{background:#0e1830;border:1px solid #24406e;border-radius:14px;padding:20px 12px;text-align:center;font-size:16px}
.tile:active{background:#1a2c52}.tile .i{font-size:24px;display:block;margin-bottom:6px}
.view{display:none}
button{background:#13203a;color:#dbe8ff;border:1px solid #24406e;border-radius:12px;padding:13px;font-size:15px;width:100%}
button:active{background:#21407a}.b{background:#1c3a6e;border-color:#2f5aa0;font-weight:600}
.row{display:flex;gap:8px;margin:8px 0}
input,textarea{flex:1;background:#0c1326;color:#dbe8ff;border:1px solid #24406e;border-radius:12px;padding:13px;font-size:15px;width:100%}
pre{background:#05080f;border:1px solid #1b2c4a;border-radius:12px;padding:11px;font-size:13px;white-space:pre-wrap;word-break:break-word;min-height:70px;color:#b6e6bd}
.net{display:flex;justify-content:space-between;padding:11px;border:1px solid #21345c;border-radius:10px;margin:6px 0;background:#0e1830}
.net small{color:#8aa0c4}.muted{color:#8aa0c4;font-size:12px;margin-top:6px}
.card{background:#0e1830;border:1px solid #21345c;border-radius:12px;padding:12px;font-size:13px;white-space:pre-wrap;color:#b6e6bd;min-height:60px}
</style></head><body><div class=wrap>
<div class=hd><span class=bk id=bk onclick=back()>&#8249;</span><b id=ttl>NOVA D1</b><span class=s id=st>...</span></div>

<div id=home class=grid>
<div class=tile onclick="op('sys')"><span class=i>&#9881;</span>System</div>
<div class=tile onclick="op('msg')"><span class=i>&#9742;</span>Messages</div>
<div class=tile onclick="op('wifi')"><span class=i>&#9776;</span>WiFi</div>
<div class=tile onclick="op('codes')"><span class=i>&#9636;</span>Codes</div>
<div class=tile onclick="op('shell')"><span class=i>&gt;_</span>Shell</div>
<div class=tile onclick="r('fetch')"><span class=i>&#9889;</span>Fetch</div>
</div>

<div id=v_sys class=view>
<div class=card id=sysc>loading...</div>
<div class=row><button onclick="r('meminfo')">Memory</button><button onclick="r('df')">Storage</button></div>
<pre id=ao>-</pre></div>

<div id=v_msg class=view>
<pre id=mb>loading...</pre>
<div class=row><input id=mt placeholder=message maxlength=120 onkeydown="if(event.key=='Enter')msend()"><button class=b onclick=msend()>Send</button></div>
<div class=muted>Broadcasts over LoRa to nearby Nova D1s.</div></div>

<div id=v_wifi class=view>
<button class=b onclick=scan()>Scan networks</button><div id=nets></div>
<div class=row><input id=ssid placeholder=SSID></div>
<div class=row><input id=pw type=password placeholder=password><button class=b onclick=conn()>Join</button></div>
<div class=muted id=wm>Pick a network or type one.</div></div>

<div id=v_codes class=view>
<div id=cl class=muted>loading...</div>
<div class=row><input id=ucat value=ir style=flex:.55><input id=uname placeholder="name e.g. tv.ir"></div>
<textarea id=ubody placeholder="paste a Flipper .ir / code / script" style=min-height:80px></textarea>
<div class=row><button class=b onclick=upl()>Upload to device</button></div>
<div class=muted id=um>Rename/delete above, or paste &amp; upload (cat: ir/subghz/lora/scripts).</div></div>

<div id=v_shell class=view>
<div class=row><input id=c placeholder="command, e.g. ls /" onkeydown="if(event.key=='Enter')run()"><button class=b onclick=run()>Run</button></div>
<pre id=o>Commands run on the device; some take a moment.</pre></div>

</div><script>
var P=localStorage.nvpin||'';
function $(i){return document.getElementById(i)}
var V=['sys','msg','wifi','codes','shell'];
var T={sys:'System',msg:'Messages',wifi:'WiFi',codes:'Codes',shell:'Shell'};
function back(){for(var v of V)$('v_'+v).style.display='none';$('home').style.display='grid';$('bk').style.display='none';$('ttl').textContent='NOVA D1'}
function op(n){$('home').style.display='none';for(var v of V)$('v_'+v).style.display=(v==n?'block':'none');$('bk').style.display='inline';$('ttl').textContent=T[n];if(n=='msg')mload();if(n=='codes')cload();if(n=='sys')sysload()}
function st(){fetch('/status').then(r=>r.json()).then(j=>{$('st').textContent=j.ip+' . '+(j.free/1024|0)+'KB'}).catch(_=>{})}
function pin(){if(!P)P=prompt('Device PIN')||'';localStorage.nvpin=P;return P}
function api(u){return fetch(u+(u.indexOf('?')<0?'?':'&')+'pin='+encodeURIComponent(pin())).then(x=>{if(x.status==403){P='';localStorage.nvpin='';throw 'PIN required'}return x})}
function r(c){if($('home').style.display!='none')op('sys');$('ao').textContent='running...';api('/cmd?c='+encodeURIComponent(c)).then(x=>x.text()).then(t=>$('ao').textContent=t).catch(e=>$('ao').textContent=e)}
function sysload(){api('/cmd?c='+encodeURIComponent('novad1 status')).then(x=>x.text()).then(t=>$('sysc').textContent=t).catch(_=>{})}
function run(){var c=$('c').value;if(!c)return;$('o').textContent='running...';api('/cmd?c='+encodeURIComponent(c)).then(x=>x.text()).then(t=>$('o').textContent=t).catch(e=>$('o').textContent=e)}
function mload(){if($('v_msg').style.display=='none')return;api('/msg').then(x=>x.json()).then(l=>{$('mb').textContent=l.map(m=>m.w+': '+m.t).join('\n')||'(no messages)'}).catch(_=>{})}
function msend(){var t=$('mt').value;if(!t)return;$('mt').value='';api('/msgsend?text='+encodeURIComponent(t)).then(_=>setTimeout(mload,300))}
function scan(){$('nets').innerHTML='<div class=muted>scanning...</div>';api('/wifiscan').then(x=>x.json()).then(l=>{$('nets').innerHTML=l.map(n=>'<div class=net onclick="document.getElementById(\'ssid\').value=\''+n.s.replace(/'/g,'')+'\'"><span>'+n.s+'</span><small>'+n.r+'dBm'+(n.k?' saved':'')+'</small></div>').join('')||'<div class=muted>none</div>'}).catch(e=>$('nets').innerHTML='<div class=muted>'+e+'</div>')}
function conn(){var s=$('ssid').value;if(!s)return;$('wm').textContent='saving...';api('/wificonnect?ssid='+encodeURIComponent(s)+'&pw='+encodeURIComponent($('pw').value)).then(x=>x.text()).then(t=>$('wm').textContent=t).catch(e=>$('wm').textContent=e)}
function cload(){if($('v_codes').style.display=='none')return;api('/codes').then(x=>x.json()).then(l=>{$('cl').innerHTML=l.map(o=>'<div class=net><span>'+o.c+'/'+o.n+'</span><small><a href=# onclick="cren(\''+o.c+'\',\''+o.n+'\');return false">rename</a> . <a href=# onclick="cdel(\''+o.c+'\',\''+o.n+'\');return false">del</a></small></div>').join('')||'<div class=muted>no codes</div>'})}
function cren(c,n){var t=prompt('New name',n);if(!t)return;api('/coderename?cat='+c+'&name='+encodeURIComponent(n)+'&to='+encodeURIComponent(t)).then(_=>cload())}
function cdel(c,n){if(!confirm('Delete '+n+'?'))return;api('/codedel?cat='+c+'&name='+encodeURIComponent(n)).then(_=>cload())}
function upl(){var c=$('ucat').value||'ir',n=$('uname').value,b=$('ubody').value;if(!n||!b){$('um').textContent='need name + content';return}fetch('/codeupload?pin='+encodeURIComponent(pin())+'&cat='+encodeURIComponent(c)+'&name='+encodeURIComponent(n),{method:'POST',body:b}).then(x=>x.text()).then(t=>{$('um').textContent=t;$('ubody').value='';cload()}).catch(e=>$('um').textContent=''+e)}
st();setInterval(st,8000);setInterval(mload,3000);
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
            req = await asyncio.wait_for(stream.read(4096), 3)
        except Exception:
            req = b''
        if not req:
            return
        line = req.split(b'\r\n', 1)[0].decode('utf-8')
        parts = line.split(' ')
        if len(parts) < 2:
            return
        method = parts[0]
        path, q = _qs(parts[1])
        if path == '/codeupload' and method == 'POST':
            pin = _reg('Apps.NovaD1_Web_PIN', '') or _reg('Apps.NovaD1_PIN', '')
            if not pin or q.get('pin', '') != pin:
                await _asend(stream, '403 Forbidden', 'text/plain', 'PIN required')
                return
            body = req.split(b'\r\n\r\n', 1)[1] if b'\r\n\r\n' in req else b''
            try:
                cl = 0
                for h in req.split(b'\r\n'):
                    if h.lower().startswith(b'content-length:'):
                        cl = int(h.split(b':', 1)[1])
                        break
                while len(body) < cl and len(body) < 16384:
                    more = await asyncio.wait_for(stream.read(1024), 3)
                    if not more:
                        break
                    body += more
            except Exception:
                pass
            try:
                import novastore
                novastore.save_code(q.get('cat', 'ir'), q.get('name', 'upload'),
                                    body.decode('utf-8'))
                await _asend(stream, '200 OK', 'text/plain', 'uploaded')
            except Exception as _e:
                await _asend(stream, '200 OK', 'text/plain', 'error: ' + str(_e)[:30])
            return
        if path == '/status':
            await _asend(stream, '200 OK', 'application/json', _status_json())
        elif path in ('/wifiscan', '/wificonnect', '/notify', '/msg', '/msgsend',
                      '/codes', '/coderename', '/codedel'):
            pin = _reg('Apps.NovaD1_Web_PIN', '') or _reg('Apps.NovaD1_PIN', '')
            if not pin or q.get('pin', '') != pin:
                await _asend(stream, '403 Forbidden', 'text/plain', 'PIN required')
            elif path == '/codes':
                await _asend(stream, '200 OK', 'application/json', _codes_json())
            elif path == '/coderename':
                try:
                    import novastore
                    novastore.rename_code(q.get('cat', ''), q.get('name', ''), q.get('to', '').strip())
                except Exception:
                    pass
                await _asend(stream, '200 OK', 'text/plain', 'renamed')
            elif path == '/codedel':
                try:
                    import novastore
                    novastore.delete_code(q.get('cat', ''), q.get('name', ''))
                except Exception:
                    pass
                await _asend(stream, '200 OK', 'text/plain', 'deleted')
            elif path == '/wifiscan':
                await _asend(stream, '200 OK', 'application/json', _wifi_scan())
            elif path == '/notify':
                try:
                    import novanotify
                    novanotify.notify(q.get('text', '').strip() or 'web ping')
                except Exception:
                    pass
                await _asend(stream, '200 OK', 'text/plain', 'sent')
            elif path == '/msg':
                await _asend(stream, '200 OK', 'application/json', _msg_json())
            elif path == '/msgsend':
                try:
                    import novamsg
                    novamsg.send(q.get('text', '').strip() or 'ping')
                except Exception:
                    pass
                await _asend(stream, '200 OK', 'text/plain', 'sent')
            elif path == '/wificonnect':
                msg = _wifi_join(q.get('ssid', '').strip(), q.get('pw', ''))
                await _asend(stream, '200 OK', 'text/plain', msg)
        elif path == '/cmd':
            # Mandatory PIN: command exec is remote root-ish, so it ALWAYS needs a
            # configured PIN (reuses the UI login PIN if no web-specific one set).
            pin = _reg('Apps.NovaD1_Web_PIN', '') or _reg('Apps.NovaD1_PIN', '')
            if not pin:
                await _asend(stream, '403 Forbidden', 'text/plain',
                             'No PIN set. On the device: reg set Apps.NovaD1_Web_PIN <digits>')
            elif q.get('pin', '') != pin:
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
