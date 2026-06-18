# Desc: WebSearch - look up information from the shell over WiFi
# File: /Packages/WebSearch/websearch.py
# Version: 1.0.0
# Author: dash1101
#
# A tiny "search engine" for RPCortex. Two commands:
#
#   search <query>      Instant answers from DuckDuckGo; if there's no direct
#                       answer it falls back to matching Wikipedia articles.
#   search -w <query>   Skip straight to the Wikipedia article list.
#   wiki <topic>        A clean one-paragraph Wikipedia summary of a topic.
#
# Both talk HTTPS to public, key-free APIs:
#   - api.duckduckgo.com  (Instant Answer API)
#   - en.wikipedia.org    (OpenSearch + REST summary)
#
# Needs WiFi. Like every HTTPS user on Pico 1 W, the TLS handshake needs a
# contiguous ~9.5 KB of heap; if it's fragmented, run 'freeup' and retry.
# TLS is encrypted but the device has no CA bundle, so certificates aren't
# verified (same as 'ask' and 'pkg') - fine for public, read-only lookups.
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only,
# no str.isalnum (the URL encoder checks characters by hand).

import sys
import gc

if '/Core' not in sys.path:
    sys.path.append('/Core')

from RPCortex import error, info, ok, warn, multi

_WRAP = 76          # wrap body text to this many columns for the terminal
_UA = 'RPCortex-Vela/1.0'

# Characters left as-is in a URL query; everything else is percent-encoded.
_SAFE = ('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
         '0123456789-_.~')


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _urlencode(s):
    """Percent-encode a query string (MicroPython str has no .isalnum)."""
    out = []
    for ch in s:
        if ch in _SAFE:
            out.append(ch)
        elif ch == ' ':
            out.append('%20')
        else:
            for b in ch.encode('utf-8'):
                out.append('%{:02X}'.format(b))
    return ''.join(out)


def _wrap(text, width=_WRAP, indent='  '):
    """Word-wrap text to width columns, printing each line via multi()."""
    line = indent
    for word in text.split():
        if len(line) + len(word) + 1 > width and line.strip():
            multi(line)
            line = indent + word
        else:
            line = (line + ' ' + word) if line.strip() else (indent + word)
    if line.strip():
        multi(line)


def _json(text):
    try:
        import ujson as _j
    except ImportError:
        import json as _j
    return _j.loads(text)


def _require_net():
    try:
        import net
        if not net.is_available():
            error("WiFi not available on this board.")
            return False
        if not net.online():
            error("Not connected to WiFi.  Run: wifi connect")
            return False
    except ImportError:
        pass   # no net module - let the socket attempt surface the error
    return True


# ---------------------------------------------------------------------------
# HTTPS GET  (mirrors ask's TLS path: heap nudge, ssl/ussl fallback, chunked)
# ---------------------------------------------------------------------------

def _parse_http(raw):
    """Split a raw HTTP response into (status, body_text), de-chunking if needed."""
    sep = raw.find(b'\r\n\r\n')
    if sep == -1:
        raise ValueError('Malformed HTTP response')
    hdr = raw[:sep].decode('utf-8', 'ignore')
    body = raw[sep + 4:]
    del raw
    gc.collect()
    try:
        status = int(hdr.split(None, 2)[1])
    except Exception:
        status = 0
    if 'chunked' in hdr.lower():
        out = b''
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
            out += rem[nl + 2:nl + 2 + sz]
            rem = rem[nl + 2 + sz + 2:]
        body = out
        del out, rem
        gc.collect()
    return status, body.decode('utf-8', 'ignore')


def _https_get(host, path, timeout=20):
    import socket
    gc.collect()
    # Heap-consolidation nudge — TLS needs a contiguous block on Pico 1 W.
    try:
        _nudge = bytearray(12288)
        del _nudge
    except MemoryError:
        pass
    gc.collect()
    if gc.mem_free() < 9500:
        raise MemoryError('Heap fragmented - run freeup and try again.')

    req = ('GET ' + path + ' HTTP/1.1\r\n'
           'Host: ' + host + '\r\n'
           'User-Agent: ' + _UA + '\r\n'
           'Accept: application/json\r\n'
           'Connection: close\r\n\r\n')

    addr = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0][-1]
    s = socket.socket()
    s.settimeout(timeout)
    s.connect(addr)
    try:
        import ssl as _ssl
    except ImportError:
        import ussl as _ssl
    try:
        s = _ssl.wrap_socket(s, server_hostname=host)
    except TypeError:
        s = _ssl.wrap_socket(s)
    s.write(req.encode('utf-8'))
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
    try:
        s.close()
    except Exception:
        pass
    gc.collect()
    return _parse_http(raw)


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------

def _wiki_opensearch(query, limit=6):
    """Return a list of (title, description, url) matching the query."""
    path = ('/w/api.php?action=opensearch&limit={}&namespace=0&format=json'
            '&search={}').format(limit, _urlencode(query))
    status, body = _https_get('en.wikipedia.org', path)
    if status != 200:
        raise OSError('Wikipedia HTTP {}'.format(status))
    data = _json(body)
    # opensearch returns [query, [titles], [descriptions], [urls]]
    titles = data[1] if len(data) > 1 else []
    descs = data[2] if len(data) > 2 else []
    urls = data[3] if len(data) > 3 else []
    out = []
    for i in range(len(titles)):
        d = descs[i] if i < len(descs) else ''
        u = urls[i] if i < len(urls) else ''
        out.append((titles[i], d, u))
    return out


def _wiki_summary(title):
    """Return (extract, url) for an exact article title, or (None, None)."""
    path = '/api/rest_v1/page/summary/' + _urlencode(title.replace(' ', '_'))
    status, body = _https_get('en.wikipedia.org', path)
    if status != 200:
        return None, None
    data = _json(body)
    extract = data.get('extract', '')
    url = ''
    try:
        url = data.get('content_urls', {}).get('desktop', {}).get('page', '')
    except Exception:
        pass
    return (extract or None), url


def _show_wiki_list(query):
    """Print Wikipedia article matches for a query. Returns count shown."""
    try:
        results = _wiki_opensearch(query)
    except Exception as e:
        error('Wikipedia search failed: {}'.format(e))
        return 0
    if not results:
        warn("No Wikipedia articles found for '{}'.".format(query))
        return 0
    info("Wikipedia matches for '{}':".format(query))
    multi('')
    for title, desc, url in results:
        multi('  \x1b[96m' + title + '\x1b[0m')
        if desc:
            _wrap(desc, indent='    ')
        if url:
            multi('    \x1b[90m' + url + '\x1b[0m')
        multi('')
    return len(results)


# ---------------------------------------------------------------------------
# DuckDuckGo Instant Answers
# ---------------------------------------------------------------------------

def _ddg(query):
    """Return the DDG Instant Answer JSON dict for a query."""
    path = ('/?q={}&format=json&no_html=1&no_redirect=1&skip_disambig=1'
            '&t=rpcortex').format(_urlencode(query))
    status, body = _https_get('api.duckduckgo.com', path)
    if status != 200:
        raise OSError('DuckDuckGo HTTP {}'.format(status))
    return _json(body)


def _show_ddg(data):
    """Print a DDG instant answer if present. Returns True if it showed one."""
    answer = (data.get('Answer') or '').strip()
    abstract = (data.get('AbstractText') or '').strip()
    heading = (data.get('Heading') or '').strip()
    if answer:
        info('Answer:')
        _wrap(answer)
        atype = data.get('AnswerType') or ''
        if atype:
            multi('  \x1b[90m(' + atype + ')\x1b[0m')
        return True
    if abstract:
        if heading:
            info(heading)
        _wrap(abstract)
        src = (data.get('AbstractSource') or '').strip()
        url = (data.get('AbstractURL') or '').strip()
        if url:
            multi('  \x1b[90m' + (src + ': ' if src else '') + url + '\x1b[0m')
        return True
    # No direct abstract - try the related topics list.
    topics = data.get('RelatedTopics') or []
    shown = 0
    for t in topics:
        if shown >= 5:
            break
        if not isinstance(t, dict):
            continue
        text = (t.get('Text') or '').strip()
        url = (t.get('FirstURL') or '').strip()
        if not text:
            continue
        if shown == 0:
            info('Related:')
            multi('')
        _wrap(text)
        if url:
            multi('  \x1b[90m' + url + '\x1b[0m')
        multi('')
        shown += 1
    return shown > 0


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _help_search():
    info("search - find information on the web")
    multi('  search <query>      instant answer (DuckDuckGo), else Wikipedia matches')
    multi('  search -w <query>   Wikipedia article list only')
    multi('  search help         this help')
    multi('  wiki <topic>        a one-paragraph Wikipedia summary')


def search(args=None):
    """Web search: DuckDuckGo instant answer, falling back to Wikipedia."""
    a = (args or '').strip()
    if not a or a.split(None, 1)[0].lower() in ('help', '-h', '--help', '?'):
        _help_search()
        return

    wiki_only = False
    if a.split(None, 1)[0].lower() in ('-w', '--wiki'):
        wiki_only = True
        a = a.split(None, 1)[1].strip() if ' ' in a else ''
        if not a:
            warn("Usage: search -w <query>")
            return

    if not _require_net():
        return

    info("Searching: {}".format(a))
    multi('')

    if wiki_only:
        _show_wiki_list(a)
        return

    # Primary: DuckDuckGo instant answers.
    try:
        data = _ddg(a)
    except MemoryError as e:
        error(str(e))
        return
    except Exception as e:
        warn('DuckDuckGo unavailable ({}); trying Wikipedia...'.format(e))
        data = None

    if data is not None and _show_ddg(data):
        multi('')
        ok('via DuckDuckGo  -  try "wiki {}" for a full summary'.format(a))
        return

    # Fallback: Wikipedia article matches.
    del data
    gc.collect()
    multi('  \x1b[90mNo instant answer - searching Wikipedia...\x1b[0m')
    multi('')
    if _show_wiki_list(a):
        ok('via Wikipedia  -  try "wiki <title>" for a summary')


def wiki(args=None):
    """Print a clean one-paragraph Wikipedia summary of a topic."""
    a = (args or '').strip()
    if not a or a.split(None, 1)[0].lower() in ('help', '-h', '--help', '?'):
        info("wiki - a one-paragraph Wikipedia summary")
        multi('  wiki <topic>     e.g.  wiki raspberry pi pico')
        multi('  search <query>   broader web search (DuckDuckGo + Wikipedia)')
        return

    if not _require_net():
        return

    info("Looking up: {}".format(a))
    # Find the best-matching article title first, then fetch its summary.
    try:
        matches = _wiki_opensearch(a, limit=1)
    except MemoryError as e:
        error(str(e))
        return
    except Exception as e:
        error('Wikipedia lookup failed: {}'.format(e))
        return

    if not matches:
        warn("No Wikipedia article found for '{}'.".format(a))
        info('Try a broader term, or:  search {}'.format(a))
        return

    title = matches[0][0]
    gc.collect()
    try:
        extract, url = _wiki_summary(title)
    except MemoryError as e:
        error(str(e))
        return
    except Exception as e:
        error('Could not load summary: {}'.format(e))
        return

    multi('')
    multi('  \x1b[96m\x1b[1m' + title + '\x1b[0m')
    multi('')
    if extract:
        _wrap(extract)
    else:
        warn('No summary text available.')
    multi('')
    if url:
        multi('  \x1b[90m' + url + '\x1b[0m')
    ok('Wikipedia')


def main(args=None):
    # So 'execute_file' / Desktop can run the module directly.
    search(args)


if __name__ == '__main__':
    search('raspberry pi pico')
