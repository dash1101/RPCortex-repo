# Desc: Ask - AI assistant for RPCortex (multi-backend, conversation mode)
# File: /Packages/Ask/ask.py
# Version: 1.3.0
# Author: dash1101
#
# Backends:
#   ollama  - self-hosted via Ollama; plain HTTP on the LAN, or HTTPS to reach
#             it off-LAN through Tailscale Funnel / a reverse proxy. No API key.
#   groq    - cloud, free tier  (console.groq.com)
#   claude  - cloud, paid       (console.anthropic.com)
#   openai  - cloud, paid       (platform.openai.com)
#
# Commands:
#   ask <question>    - single question, no history
#   ask               - conversation mode (multi-turn, 'exit' or blank to quit)
#   ask --settings    - arrow-key settings panel (backend, model, key, host)
#   ask --setup       - run the first-time backend setup wizard
#   ask --status      - show current config
#   ask --reset       - wipe all Ask config from registry

import sys
import gc

if '/Core' not in sys.path:
    sys.path.append('/Core')

from RPCortex import error, info, ok, warn, multi, inpt
import regedit

_DEFAULTS = {
    'ollama': 'llama3.2',
    'groq':   'llama-3.3-70b-versatile',
    'claude': 'claude-haiku-4-5-20251001',
    'openai': 'gpt-4o-mini',
}

_REG_BACKEND     = 'Apps.Ask_Backend'
_REG_MODEL       = 'Apps.Ask_Model'
_REG_OLLAMA_HOST = 'Apps.Ask_Ollama_Host'
_REG_KEY_GROQ    = 'Apps.Ask_Key_Groq'
_REG_KEY_CLAUDE  = 'Apps.Ask_Key_Claude'
_REG_KEY_OPENAI  = 'Apps.Ask_Key_OpenAI'

_BACKENDS = ('ollama', 'groq', 'claude', 'openai')
_KEY_REG  = {'groq': _REG_KEY_GROQ, 'claude': _REG_KEY_CLAUDE, 'openai': _REG_KEY_OPENAI}

# ANSI styling for the settings panel (mirrors Core settings.py).
_CY = '\x1b[96m'; _GR = '\x1b[92m'; _YL = '\x1b[93m'
_DG = '\x1b[90m'; _WH = '\x1b[97m'; _BD = '\x1b[1m'; _R = '\x1b[0m'
_PW = 64          # panel width

# Max conversation turns kept in history (each turn = 1 user + 1 assistant msg).
# Keeps memory use predictable on Pico 1.
_MAX_TURNS = 4


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _rget(key):
    try:
        v = regedit.read(key)
        return v if v else None
    except Exception:
        return None


def _rset(key, val):
    try:
        regedit.save(key, val)
    except Exception as e:
        warn('Registry write failed: ' + str(e))


# ---------------------------------------------------------------------------
# Shared HTTP response parser
# ---------------------------------------------------------------------------

def _parse_response(raw):
    try:
        import ujson as json
    except ImportError:
        import json

    sep = raw.find(b'\r\n\r\n')
    if sep == -1:
        raise Exception('Malformed HTTP response')

    hdr  = raw[:sep].decode('utf-8', 'ignore')
    body = raw[sep + 4:]
    del raw
    gc.collect()

    try:
        status = int(hdr.split(None, 2)[1])
    except Exception:
        status = 0

    if 'chunked' in hdr.lower():
        decoded = b''
        rem = body
        while rem:
            nl = rem.find(b'\r\n')
            if nl == -1:
                break
            try:
                sz = int(rem[:nl], 16)
            except Exception:
                break
            if sz == 0:
                break
            decoded += rem[nl + 2:nl + 2 + sz]
            rem = rem[nl + 2 + sz + 2:]
        body = decoded
        del decoded, rem
        gc.collect()

    try:
        data = json.loads(body.decode('utf-8', 'ignore'))
    except Exception:
        snippet = body[:80].decode('utf-8', 'ignore')
        raise Exception('JSON parse failed: ' + snippet)

    return status, data


# ---------------------------------------------------------------------------
# Plain HTTP POST  (Ollama — no TLS, works great on Pico 1)
# ---------------------------------------------------------------------------

def _http_post(host, port, path, payload_bytes):
    import socket

    headers_str = (
        'POST ' + path + ' HTTP/1.1\r\n'
        'Host: ' + host + ':' + str(port) + '\r\n'
        'Content-Type: application/json\r\n'
        'Content-Length: ' + str(len(payload_bytes)) + '\r\n'
        'Connection: close\r\n'
        '\r\n'
    )
    request = headers_str.encode('utf-8') + payload_bytes
    del headers_str

    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    s = socket.socket()
    s.settimeout(60)
    s.connect(addr)
    s.write(request)
    del request

    raw = b''
    while True:
        try:
            chunk = s.read(1024)
        except OSError:
            break
        if not chunk:
            break
        raw += chunk
    s.close()
    gc.collect()
    return _parse_response(raw)


# ---------------------------------------------------------------------------
# HTTPS POST  (Claude, Groq, OpenAI)
# ---------------------------------------------------------------------------

def _https_post(host, path, extra_headers, payload_bytes, port=443):
    import socket
    gc.collect()

    try:
        _nudge = bytearray(12288)
        del _nudge
    except MemoryError:
        pass
    gc.collect()

    if gc.mem_free() < 9500:
        raise MemoryError('Heap fragmented. Run freeup and try again.')

    headers_str = (
        'POST ' + path + ' HTTP/1.1\r\n'
        'Host: ' + host + '\r\n'
        'Content-Type: application/json\r\n'
        'Content-Length: ' + str(len(payload_bytes)) + '\r\n'
    )
    for k, v in extra_headers.items():
        headers_str += k + ': ' + v + '\r\n'
    headers_str += 'Connection: close\r\n\r\n'

    request = headers_str.encode('utf-8') + payload_bytes
    del headers_str

    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    s = socket.socket()
    s.settimeout(20)
    s.connect(addr)

    try:
        import ssl as _ssl
    except ImportError:
        import ussl as _ssl
    try:
        s = _ssl.wrap_socket(s, server_hostname=host)
    except TypeError:
        s = _ssl.wrap_socket(s)

    s.write(request)
    del request
    gc.collect()

    raw = b''
    while True:
        try:
            chunk = s.read(1024)
        except OSError:
            break
        if not chunk:
            break
        raw += chunk
    s.close()
    gc.collect()
    return _parse_response(raw)


# ---------------------------------------------------------------------------
# Backend: Ollama  (uses /api/chat for multi-turn support)
# ---------------------------------------------------------------------------

def _do_ollama(messages, model, host_port):
    try:
        import ujson as json
    except ImportError:
        import json

    # The host may be a plain LAN address ('192.168.1.100:11434') OR a full
    # URL. An https:// URL routes over TLS — that's how you reach an Ollama
    # exposed off-LAN via Tailscale Funnel/Serve ('https://box.tailnet.ts.net')
    # or any HTTPS reverse proxy, so 'ask' works when you're away.
    use_https = False
    h = host_port.strip()
    if h.startswith('https://'):
        use_https = True
        h = h[8:]
    elif h.startswith('http://'):
        h = h[7:]
    h = h.rstrip('/')
    if '/' in h:                       # drop any path; we always POST /api/chat
        h = h.split('/', 1)[0]
    if ':' in h:
        host, p = h.rsplit(':', 1)
        try:
            port = int(p)
        except Exception:
            port = 443 if use_https else 11434
    else:
        host = h
        port = 443 if use_https else 11434

    payload = json.dumps({
        'model': model,
        'messages': messages,
        'stream': False,
    }).encode('utf-8')

    if use_https:
        status, data = _https_post(host, '/api/chat', {}, payload, port=port)
    else:
        status, data = _http_post(host, port, '/api/chat', payload)

    if status == 200:
        return data['message']['content']
    elif status == 404:
        raise Exception(
            "Model '{}' not found. Run on your server: ollama pull {}".format(model, model)
        )
    else:
        raise Exception('Ollama HTTP {}: {}'.format(status, str(data)[:100]))


# ---------------------------------------------------------------------------
# Backend: Groq / OpenAI  (shared — both use the OpenAI chat format)
# ---------------------------------------------------------------------------

def _do_openai_compat(messages, model, api_key, host, path):
    try:
        import ujson as json
    except ImportError:
        import json

    payload = json.dumps({
        'model': model,
        'max_tokens': 512,
        'messages': messages,
    }).encode('utf-8')

    status, data = _https_post(host, path, {
        'Authorization': 'Bearer ' + api_key,
    }, payload)

    if status == 200:
        return data['choices'][0]['message']['content']
    elif status == 401:
        raise Exception('Invalid API key. Run: ask --settings')
    elif status == 429:
        raise Exception('Rate limited. Wait and retry.')
    else:
        msg = ''
        try:
            msg = data.get('error', {}).get('message', '')
        except Exception:
            pass
        raise Exception('HTTP {}: {}'.format(status, msg))


# ---------------------------------------------------------------------------
# Backend: Claude  (Anthropic format)
# ---------------------------------------------------------------------------

def _do_claude(messages, model, api_key):
    try:
        import ujson as json
    except ImportError:
        import json

    payload = json.dumps({
        'model': model,
        'max_tokens': 512,
        'messages': messages,
    }).encode('utf-8')

    status, data = _https_post('api.anthropic.com', '/v1/messages', {
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    }, payload)

    if status == 200:
        return data['content'][0]['text']
    elif status == 401:
        raise Exception('Invalid Claude API key. Run: ask --settings')
    elif status == 429:
        raise Exception('Claude rate limited. Wait and retry.')
    else:
        msg = ''
        try:
            msg = data.get('error', {}).get('message', '')
        except Exception:
            pass
        raise Exception('Claude HTTP {}: {}'.format(status, msg))


# ---------------------------------------------------------------------------
# Dispatch a single turn to the configured backend
# ---------------------------------------------------------------------------

def _require_network():
    """Return True if network is available and connected; False with error message otherwise."""
    try:
        import net
        if not net.is_available():
            error("WiFi not available on this board.")
            return False
        if not net.online():
            error("Not connected to WiFi. Run: wifi connect")
            return False
    except ImportError:
        pass   # no net module — let the socket call try anyway
    return True


def _send(messages, backend, model):
    if backend == 'ollama':
        host = _rget(_REG_OLLAMA_HOST)
        if not host:
            raise Exception('No Ollama host set. Run: ask --settings')
        return _do_ollama(messages, model, host)

    elif backend == 'groq':
        key = _rget(_REG_KEY_GROQ)
        if not key:
            raise Exception('No Groq API key. Run: ask --settings')
        return _do_openai_compat(messages, model, key,
                                  'api.groq.com', '/openai/v1/chat/completions')

    elif backend == 'claude':
        key = _rget(_REG_KEY_CLAUDE)
        if not key:
            raise Exception('No Claude API key. Run: ask --settings')
        return _do_claude(messages, model, key)

    elif backend == 'openai':
        key = _rget(_REG_KEY_OPENAI)
        if not key:
            raise Exception('No OpenAI API key. Run: ask --settings')
        return _do_openai_compat(messages, model, key,
                                  'api.openai.com', '/v1/chat/completions')

    else:
        raise Exception('Unknown backend: ' + backend + '. Run: ask --settings')


# ---------------------------------------------------------------------------
# Setup wizard  (first-time or switching backend)
# ---------------------------------------------------------------------------

def _setup():
    multi('')
    multi('  Ask  —  backend setup')
    multi('  ' + '-' * 38)
    multi('')
    multi('  [1] Ollama   self-hosted, free, no API key')
    multi('  [2] Groq     cloud, free tier available')
    multi('  [3] Claude   cloud, paid  (Anthropic)')
    multi('  [4] OpenAI   cloud, paid')
    multi('  [q] Cancel')
    multi('')

    choice = inpt('  Choose: ').strip().lower()
    if not choice or choice == 'q':
        return

    if choice == '1':
        multi('')
        info('Ollama must be running on your server and exposed on the network.')
        info('By default Ollama only listens on localhost. To expose it:')
        info('  Windows:  set OLLAMA_HOST=0.0.0.0  &&  ollama serve')
        info('  Linux:    OLLAMA_HOST=0.0.0.0 ollama serve')
        info('Then pull a model:  ollama pull llama3.2')
        multi('')
        info('Reaching it from another network? Put Ollama behind Tailscale')
        info('Funnel (or any HTTPS proxy) and enter the https:// URL below.')
        multi('')
        host = inpt('  Server (192.168.1.100:11434  or  https://box.ts.net): ').strip()
        if not host:
            error('No address entered.')
            return
        if '://' not in host and ':' not in host:
            host = host + ':11434'
        model = inpt('  Model name [llama3.2]: ').strip() or 'llama3.2'
        _rset(_REG_BACKEND, 'ollama')
        _rset(_REG_OLLAMA_HOST, host)
        _rset(_REG_MODEL, model)
        multi('')
        ok('Backend: ollama  |  host: {}  |  model: {}'.format(host, model))

    elif choice == '2':
        multi('')
        info('Get a free Groq key at: console.groq.com')
        info('Free models: llama-3.3-70b-versatile, llama-3.1-8b-instant')
        multi('')
        key = inpt('  Groq API key: ').strip()
        if not key:
            error('No key entered.')
            return
        model = inpt('  Model [llama-3.3-70b-versatile]: ').strip() or 'llama-3.3-70b-versatile'
        _rset(_REG_BACKEND, 'groq')
        _rset(_REG_KEY_GROQ, key)
        _rset(_REG_MODEL, model)
        multi('')
        ok('Backend: groq  |  model: {}'.format(model))

    elif choice == '3':
        multi('')
        info('Get a Claude key at: console.anthropic.com')
        multi('')
        key = inpt('  Anthropic API key: ').strip()
        if not key:
            error('No key entered.')
            return
        model = inpt('  Model [claude-haiku-4-5-20251001]: ').strip() or 'claude-haiku-4-5-20251001'
        _rset(_REG_BACKEND, 'claude')
        _rset(_REG_KEY_CLAUDE, key)
        _rset(_REG_MODEL, model)
        multi('')
        ok('Backend: claude  |  model: {}'.format(model))

    elif choice == '4':
        multi('')
        info('Get an OpenAI key at: platform.openai.com')
        multi('')
        key = inpt('  OpenAI API key: ').strip()
        if not key:
            error('No key entered.')
            return
        model = inpt('  Model [gpt-4o-mini]: ').strip() or 'gpt-4o-mini'
        _rset(_REG_BACKEND, 'openai')
        _rset(_REG_KEY_OPENAI, key)
        _rset(_REG_MODEL, model)
        multi('')
        ok('Backend: openai  |  model: {}'.format(model))

    else:
        error('Unknown choice.')


# ---------------------------------------------------------------------------
# Settings menu  (quick changes without re-running full wizard)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Settings panel  (arrow-key TUI, mirrors the Core 'settings' app)
# ---------------------------------------------------------------------------

_p_idx = {}
_p_nlines = 0
_p_sel = 'b'
_P_PROMPT = 'Choice: '


def _p_backend():
    return _rget(_REG_BACKEND) or ''


def _p_nav():
    """Selectable row keys; the host/key row depends on the backend."""
    b = _p_backend()
    keys = ['b', 'm']
    if b == 'ollama':
        keys.append('h')
    elif b in _KEY_REG:
        keys.append('k')
    keys += ['w', 'x']
    return keys


def _p_lead(key):
    return (_CY + _BD + '> ' + _R) if key == _p_sel else '  '


def _p_row(key, label, value, vcol=None, note=''):
    vcol = vcol or _YL
    ntxt = ('   ' + _DG + note + _R) if note else ''
    return (_p_lead(key) + _WH + '[' + key + ']' + _R + ' ' +
            '{:<14}'.format(label) + ' : ' + vcol + value + _R + ntxt)


def _p_sec(title):
    prefix = '== {} '.format(title)
    return _CY + prefix + _DG + '=' * max(0, _PW - len(prefix)) + _R


def _p_row_for(key):
    b = _p_backend()
    if key == 'b':
        return _p_row('b', 'Backend', b or '(not set)',
                      _GR if b else _DG, 'Enter cycles')
    if key == 'm':
        model = _rget(_REG_MODEL) or _DEFAULTS.get(b, '(default)')
        return _p_row('m', 'Model', model)
    if key == 'h':
        host = _rget(_REG_OLLAMA_HOST) or '(not set)'
        return _p_row('h', 'Ollama host', host, _YL if _rget(_REG_OLLAMA_HOST) else _DG,
                      'https:// = remote/Tailscale')
    if key == 'k':
        keyset = _rget(_KEY_REG.get(b, '')) if b in _KEY_REG else None
        return _p_row('k', 'API key', 'set' if keyset else '(not set)',
                      _GR if keyset else _DG)
    if key == 'w':
        return _p_row('w', 'Setup wizard', 'run', _DG)
    if key == 'x':
        return _p_row('x', 'Clear config', '', _DG)
    return ''


def _p_build():
    lines = []
    idx = {}
    b = _p_backend()
    lines.append('  ' + _WH + _BD + 'Ask  -  AI settings' + _R)
    lines.append(_DG + '=' * _PW + _R)
    lines.append('')
    lines.append(_p_sec('BACKEND'))
    idx['b'] = len(lines); lines.append(_p_row_for('b'))
    idx['m'] = len(lines); lines.append(_p_row_for('m'))
    if b == 'ollama':
        idx['h'] = len(lines); lines.append(_p_row_for('h'))
    elif b in _KEY_REG:
        idx['k'] = len(lines); lines.append(_p_row_for('k'))
    lines.append('')
    lines.append(_p_sec('ACTIONS'))
    idx['w'] = len(lines); lines.append(_p_row_for('w'))
    idx['x'] = len(lines); lines.append(_p_row_for('x'))
    lines.append('')
    lines.append(_DG + '=' * _PW + _R)
    lines.append('  ' + _DG + 'Up/Down' + _R + ' move   ' + _DG + 'Enter' + _R +
                 ' change   ' + _DG + 'letter' + _R + ' jump   ' + _DG + '[q]' + _R + ' quit')
    return lines, idx


def _p_full_draw():
    global _p_idx, _p_nlines
    lines, _p_idx = _p_build()
    _p_nlines = len(lines)
    out = ['\x1b[2J\x1b[H\x1b[?25h']
    for ln in lines:
        out.append(ln); out.append('\r\n')
    out.append(_P_PROMPT)
    sys.stdout.write(''.join(out))


def _p_update(key):
    i = _p_idx.get(key)
    if i is None:
        return
    up = _p_nlines - i
    sys.stdout.write('\x1b[{}A\r'.format(up))
    sys.stdout.write(_p_row_for(key) + '\x1b[K')
    sys.stdout.write('\x1b[{}B\r'.format(up))
    sys.stdout.write(_P_PROMPT)


def _p_edit(key):
    """Edit a value via a full-screen prompt; returns True if rows may have changed."""
    b = _p_backend()
    if key == 'b':
        # Cycle to the next backend (changes which extra row shows). No clear -
        # the caller repaints, so cycling stays flicker-free.
        try:
            nxt = _BACKENDS[(_BACKENDS.index(b) + 1) % len(_BACKENDS)]
        except ValueError:
            nxt = _BACKENDS[0]
        _rset(_REG_BACKEND, nxt)
        return True
    sys.stdout.write('\x1b[2J\x1b[H')
    if key == 'm':
        cur = _rget(_REG_MODEL) or _DEFAULTS.get(b, '')
        info('Change model')
        multi('  Current: ' + (cur or '(default)'))
        val = inpt('New model (blank = keep)').strip()
        if val:
            _rset(_REG_MODEL, val)
    elif key == 'h':
        cur = _rget(_REG_OLLAMA_HOST) or ''
        info('Ollama host')
        multi('  LAN:     192.168.1.100:11434')
        multi('  Remote:  https://box.tailnet.ts.net   (Tailscale Funnel / proxy)')
        multi('  Current: ' + (cur or '(not set)'))
        val = inpt('New host (blank = keep)').strip()
        if val:
            if '://' not in val and ':' not in val:
                val = val + ':11434'         # bare IP -> default Ollama port
            _rset(_REG_OLLAMA_HOST, val)
    elif key == 'k':
        info('Set API key for ' + (b or '?'))
        val = inpt('New API key (blank = keep)').strip()
        if val and b in _KEY_REG:
            _rset(_KEY_REG[b], val)
    elif key == 'w':
        _setup()
        return True
    elif key == 'x':
        warn('Clear ALL Ask config?')
        if inpt('Type yes to confirm').strip().lower() in ('y', 'yes'):
            for k in (_REG_BACKEND, _REG_MODEL, _REG_OLLAMA_HOST,
                      _REG_KEY_GROQ, _REG_KEY_CLAUDE, _REG_KEY_OPENAI):
                try:
                    regedit.save(k, '')
                except Exception:
                    pass
            ok('All Ask config cleared.')
            sys.stdin.read(1)
        return True
    return False


def _settings():
    """Arrow-key settings panel for the Ask package."""
    global _p_sel
    if _p_sel not in _p_nav():
        _p_sel = 'b'
    _p_full_draw()
    while True:
        try:
            ch = sys.stdin.read(1)
        except Exception:
            break

        if ch == '\x1b':                      # arrows / bare ESC quits
            try:
                if sys.stdin.read(1) == '[':
                    a = sys.stdin.read(1)
                    if a in ('A', 'B'):
                        nav = _p_nav()
                        old = _p_sel
                        i = nav.index(_p_sel) if _p_sel in nav else 0
                        i = (i - 1) % len(nav) if a == 'A' else (i + 1) % len(nav)
                        _p_sel = nav[i]
                        _p_update(old)
                        _p_update(_p_sel)
                else:
                    break
            except Exception:
                pass
            continue

        if ch in ('q', 'Q', '\x03'):
            break

        act = _p_sel if ch in ('\r', '\n') else ch.lower()
        if act not in _p_nav():
            if ch in ('r', 'R'):
                _p_full_draw()
            continue
        old = _p_sel
        _p_sel = act
        if old != _p_sel:
            _p_update(old)
        _p_edit(act)                      # edits use a full-screen prompt...
        if _p_sel not in _p_nav():        # backend change can drop the host/key row
            _p_sel = 'b'
        _p_full_draw()                    # ...so always repaint afterwards

    sys.stdout.write('\x1b[2J\x1b[H')
    ok('Ask settings saved.')


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def _status():
    backend = _rget(_REG_BACKEND) or '(not configured)'
    model   = _rget(_REG_MODEL)   or _DEFAULTS.get(backend, '(default)')
    multi('')
    multi('  Ask  —  current config')
    multi('  ' + '-' * 38)
    multi('  Backend : ' + backend)
    multi('  Model   : ' + model)
    if backend == 'ollama':
        multi('  Host    : ' + (_rget(_REG_OLLAMA_HOST) or '(not set)'))
    elif backend in ('groq', 'claude', 'openai'):
        km = {'groq': _REG_KEY_GROQ, 'claude': _REG_KEY_CLAUDE, 'openai': _REG_KEY_OPENAI}
        multi('  API key : ' + ('set' if _rget(km[backend]) else '(not set)'))
    multi('')
    multi('  ask --settings  to change anything')
    multi('')


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def ask(args=None):
    # Flag commands
    if args:
        flag = args.split(None, 1)[0].lower()
        if flag in ('help', '-h', '--help', '?'):
            info("ask - ask an AI a question from the shell")
            multi('  ask "your question"   send a prompt to the configured backend')
            multi("  ask                   conversation mode (multi-turn)")
            multi("  ask --setup           pick a backend + key (Ollama/Groq/Claude/OpenAI)")
            multi("  ask --settings        open the settings panel (arrow keys)")
            multi("  ask --status          show the current backend + model")
            multi("  ask --reset           clear all Ask config")
            multi('')
            multi("  Ollama can be a LAN address (192.168.1.x:11434) or an")
            multi("  https:// URL (Tailscale Funnel/proxy) to reach it when away.")
            return
        if flag == '--settings':
            _settings()
            return
        if flag == '--setup':
            _setup()
            return
        if flag == '--status':
            _status()
            return
        if flag == '--reset':
            for k in (_REG_BACKEND, _REG_MODEL, _REG_OLLAMA_HOST,
                      _REG_KEY_GROQ, _REG_KEY_CLAUDE, _REG_KEY_OPENAI):
                try:
                    regedit.save(k, '')
                except Exception:
                    pass
            ok('All Ask config cleared. Run: ask --setup')
            return

    # First-run: no backend configured
    backend = _rget(_REG_BACKEND)
    if not backend:
        warn('Ask is not configured yet.')
        _setup()
        backend = _rget(_REG_BACKEND)
        if not backend:
            return

    model = _rget(_REG_MODEL) or _DEFAULTS.get(backend, 'default')

    if not _require_network():
        return

    # --- Single-shot mode (question passed as arg) ---
    if args and args.strip():
        question = args.strip()
        info('Thinking...')
        gc.collect()
        try:
            text = _send([{'role': 'user', 'content': question}], backend, model)
        except MemoryError as e:
            error(str(e))
            return
        except Exception as e:
            error(str(e))
            return
        multi('')
        for line in text.split('\n'):
            multi(line)
        multi('')
        ok(backend + ' / ' + model)
        return

    # --- Conversation mode (no args — multi-turn with history) ---
    history = []
    multi('')
    info('Conversation mode  [' + backend + ' / ' + model + ']')
    info('Type your message. Empty line or "exit" to quit.')
    multi('')

    while True:
        try:
            question = inpt('You: ').strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not question or question.lower() in ('exit', 'quit', 'bye'):
            break

        # Build messages: history + new user turn
        messages = history + [{'role': 'user', 'content': question}]

        info('Thinking...')
        gc.collect()

        try:
            text = _send(messages, backend, model)
        except MemoryError as e:
            error(str(e))
            warn('History cleared to free memory. Try again.')
            history = []
            gc.collect()
            continue
        except Exception as e:
            error(str(e))
            continue

        multi('')
        for line in text.split('\n'):
            multi(line)
        multi('')

        # Add this exchange to history
        history.append({'role': 'user', 'content': question})
        history.append({'role': 'assistant', 'content': text})

        # Trim history to keep memory bounded (drop oldest turn = 2 messages)
        if len(history) > _MAX_TURNS * 2:
            history = history[2:]
            gc.collect()

    ok('Session ended.')
