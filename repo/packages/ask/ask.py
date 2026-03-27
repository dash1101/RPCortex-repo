# Desc: Ask — AI assistant for RPCortex (multi-backend, conversation mode)
# File: /Packages/Ask/ask.py
# Version: 1.2.0
# Author: dash1101
#
# Backends:
#   ollama  — self-hosted via Ollama, plain HTTP, no API key  (try this first)
#   groq    — cloud, free tier  (console.groq.com)
#   claude  — cloud, paid       (console.anthropic.com)
#   openai  — cloud, paid       (platform.openai.com)
#
# Commands:
#   ask <question>    — single question, no history
#   ask               — conversation mode (multi-turn, 'exit' or blank to quit)
#   ask --settings    — settings menu (change model, key, backend, host)
#   ask --setup       — run the first-time backend setup wizard
#   ask --status      — show current config
#   ask --reset       — wipe all Ask config from registry

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

def _https_post(host, path, extra_headers, payload_bytes):
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

    addr = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0][-1]
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

    if ':' in host_port:
        parts = host_port.rsplit(':', 1)
        host = parts[0]
        try:
            port = int(parts[1])
        except Exception:
            port = 11434
    else:
        host = host_port
        port = 11434

    payload = json.dumps({
        'model': model,
        'messages': messages,
        'stream': False,
    }).encode('utf-8')

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
        host = inpt('  Server address (e.g. 192.168.1.100:11434): ').strip()
        if not host:
            error('No address entered.')
            return
        if ':' not in host:
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

def _settings():
    backend = _rget(_REG_BACKEND) or '(not set)'
    model   = _rget(_REG_MODEL)   or _DEFAULTS.get(backend, '?')

    while True:
        multi('')
        multi('  Ask  —  settings')
        multi('  ' + '-' * 38)
        multi('  Backend : ' + backend)
        multi('  Model   : ' + model)
        if backend == 'ollama':
            multi('  Host    : ' + (_rget(_REG_OLLAMA_HOST) or '(not set)'))
        elif backend in ('groq', 'claude', 'openai'):
            km = {'groq': _REG_KEY_GROQ, 'claude': _REG_KEY_CLAUDE, 'openai': _REG_KEY_OPENAI}
            multi('  API key : ' + ('set' if _rget(km[backend]) else '(not set)'))
        multi('')
        multi('  [1] Switch backend')
        multi('  [2] Change model')
        if backend == 'ollama':
            multi('  [3] Change Ollama host')
        elif backend in ('groq', 'claude', 'openai'):
            multi('  [3] Update API key')
        else:
            multi('  [3] Set API key / host')
        multi('  [4] Clear all Ask settings')
        multi('  [q] Back')
        multi('')

        choice = inpt('  Choose: ').strip().lower()

        if not choice or choice == 'q':
            break

        elif choice == '1':
            _setup()
            backend = _rget(_REG_BACKEND) or backend
            model   = _rget(_REG_MODEL)   or model

        elif choice == '2':
            new_model = inpt('  New model name [{}]: '.format(model)).strip()
            if new_model:
                model = new_model
                _rset(_REG_MODEL, model)
                ok('Model set to: ' + model)

        elif choice == '3':
            if backend == 'ollama':
                cur = _rget(_REG_OLLAMA_HOST) or ''
                new_host = inpt('  Ollama host [{}]: '.format(cur or '192.168.1.x:11434')).strip()
                if new_host:
                    if ':' not in new_host:
                        new_host = new_host + ':11434'
                    _rset(_REG_OLLAMA_HOST, new_host)
                    ok('Ollama host set to: ' + new_host)
            elif backend in ('groq', 'claude', 'openai'):
                km = {'groq': _REG_KEY_GROQ, 'claude': _REG_KEY_CLAUDE, 'openai': _REG_KEY_OPENAI}
                new_key = inpt('  New API key: ').strip()
                if new_key:
                    _rset(km[backend], new_key)
                    ok('API key updated.')
            else:
                warn('Configure a backend first with option [1].')

        elif choice == '4':
            confirm = inpt('  Clear all Ask settings? [y/N]: ').strip().lower()
            if confirm == 'y':
                for k in (_REG_BACKEND, _REG_MODEL, _REG_OLLAMA_HOST,
                          _REG_KEY_GROQ, _REG_KEY_CLAUDE, _REG_KEY_OPENAI):
                    try:
                        regedit.delete(k)
                    except Exception:
                        pass
                ok('All Ask settings cleared.')
                backend = '(not set)'
                model   = '?'

        else:
            error('Unknown option.')


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
