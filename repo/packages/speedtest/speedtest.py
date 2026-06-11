# Desc: SpeedTest — measure WiFi latency and download throughput
# File: /Packages/SpeedTest/speedtest.py
# Version: 1.0.0
# Author: dash1101
#
# A lightweight network speed test for RPCortex. Latency uses a TCP connect
# (real ICMP isn't available on MicroPython); throughput streams a test file
# and discards it chunk-by-chunk, so it never accumulates the body in RAM and
# is safe on a 264 KB Pico.
#
# Usage:
#   speedtest                 latency + a ~1 MB download from the default host
#   speedtest ping [host]     latency only (default 1.1.1.1)
#   speedtest down [url]      throughput only (default Tele2 1 MB over HTTP)
#   speedtest info            notes and the default endpoints
#
# Notes:
#   - The download test uses plain HTTP on purpose — TLS needs ~9.5 KB of
#     contiguous heap on a Pico 1 W and would skew a throughput result.
#   - Pass your own http:// URL to test against a closer mirror.

import sys

if '/Core' not in sys.path:
    sys.path.append('/Core')

from RPCortex import error, info, ok, warn, multi

_DEFAULT_PING = '1.1.1.1'
_DEFAULT_URL  = 'http://speedtest.tele2.net/1MB.zip'


def _online():
    """True if WiFi is up; prints guidance and returns False otherwise."""
    try:
        import net
    except ImportError:
        return True   # no net module — let the socket call try anyway
    if not net.is_available():
        error("WiFi not available on this board.")
        return False
    try:
        if not net.online():
            error("Not connected to WiFi. Run: wifi connect")
            return False
    except Exception:
        pass
    return True


def _split_url(url):
    """Return (host, port, path) for an http:// URL (TLS not supported here)."""
    if url.startswith('https://'):
        return None
    if url.startswith('http://'):
        url = url[7:]
    slash = url.find('/')
    if slash == -1:
        host, path = url, '/'
    else:
        host, path = url[:slash], url[slash:]
    port = 80
    if ':' in host:
        host, p = host.split(':', 1)
        try:
            port = int(p)
        except ValueError:
            port = 80
    return host, port, path


def _human_rate(bytes_, ms):
    if ms <= 0:
        return '?'
    kbps = (bytes_ / 1024.0) / (ms / 1000.0)
    if kbps >= 1024:
        return '{:.2f} MB/s  ({:.1f} Mbit/s)'.format(kbps / 1024.0, kbps * 8 / 1024.0)
    return '{:.1f} KB/s  ({:.2f} Mbit/s)'.format(kbps, kbps * 8 / 1024.0)


def _download(url):
    """Stream a URL's body, discarding it, and report bytes + elapsed ms."""
    import socket
    import utime
    import gc

    parsed = _split_url(url)
    if parsed is None:
        error("The download test only supports http:// URLs.")
        info("HTTPS skews throughput on a Pico (TLS heap). Use an http:// mirror.")
        return
    host, port, path = parsed

    info("Downloading {} ...".format(url))
    try:
        addr = socket.getaddrinfo(host, port)[0][-1]
    except Exception as e:
        error("Cannot resolve '{}': {}".format(host, e))
        return

    s = socket.socket()
    try:
        s.settimeout(15)
    except Exception:
        pass

    total = 0
    t0 = utime.ticks_ms()
    try:
        s.connect(addr)
        req = ('GET {} HTTP/1.0\r\nHost: {}\r\n'
               'User-Agent: RPCortex-SpeedTest/1.0\r\n'
               'Connection: close\r\n\r\n').format(path, host)
        s.send(req.encode())

        buf = bytearray(1024)
        header_done = False
        body_started = 0
        while True:
            n = s.readinto(buf)
            if not n:
                break
            if not header_done:
                # Find the end of the HTTP headers, count only body bytes.
                chunk = bytes(buf[:n])
                idx = chunk.find(b'\r\n\r\n')
                if idx != -1:
                    header_done = True
                    body_started = n - (idx + 4)
                    total += body_started
                continue
            total += n
        elapsed = utime.ticks_diff(utime.ticks_ms(), t0)
    except OSError as e:
        error("Download failed: {}".format(e))
        return
    finally:
        try:
            s.close()
        except Exception:
            pass
        gc.collect()

    if total <= 0:
        warn("No data received — the server may have returned an error page.")
        return
    ok("Downloaded {:.1f} KB in {:.2f} s".format(total / 1024.0, elapsed / 1000.0))
    ok("Download speed: {}".format(_human_rate(total, elapsed)))


def _ping(host):
    try:
        import net
    except ImportError:
        error("net module unavailable.")
        return
    net.ping(host, count=4, port=80)


def _info():
    info("=== SpeedTest ===")
    multi("  ping [host]   TCP latency test     (default {})".format(_DEFAULT_PING))
    multi("  down [url]    download throughput  (default Tele2 1 MB)")
    multi("  (no args)     latency, then download")
    multi("")
    multi("  Default file : {}".format(_DEFAULT_URL))
    multi("  HTTPS URLs aren't used for throughput — TLS heap skews the result.")
    multi("  Tip: pass a nearby http:// mirror for a more accurate number.")


def speedtest(args=None):
    sub = ''
    rest = ''
    if args and args.strip():
        parts = args.split(None, 1)
        sub = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ''

    if sub == 'info':
        _info()
        return

    if not _online():
        return

    if sub == 'ping':
        _ping(rest or _DEFAULT_PING)
        return

    if sub == 'down':
        _download(rest or _DEFAULT_URL)
        return

    if sub == '':
        # Full test: latency then throughput.
        _ping(_DEFAULT_PING)
        multi("")
        _download(_DEFAULT_URL)
        return

    # `speedtest <url>` shorthand for a download test.
    if sub.startswith('http'):
        _download(args.strip())
        return

    error("Unknown subcommand '{}'. Try 'speedtest info'.".format(sub))
