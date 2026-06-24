# Desc: Nova D1 background WiFi manager — non-blocking autoconnect + status.
# File: /Packages/NovaD1/novawifi.py
#
# The OS POST autoconnect calls net.connect_saved(timeout=15) — a 15s BLOCKING
# wait at boot when no AP is found, which is why the UI was slow / didn't come up.
# novad1 setup turns that off; this manager does the same job COOPERATIVELY on the
# event loop: kick wlan.connect, poll isconnected() with sleep_ms yields, drive a
# 3-state icon ('off' / 'connecting' / 'connected') the status bar reads. It also
# tolerates the OS autoconnect still being on (existing installs) — if WLAN is
# already connected it just reflects that, never double-connects.
# MicroPython-safe: no f-strings.

_state = 'off'
_started = False


def state():
    return _state


def _saved():
    try:
        import net
        return net._read_networks() or []
    except Exception:
        return []


async def manager():
    """Run forever as a background task: keep WiFi connected, update state()."""
    global _state, _started
    if _started:
        return
    _started = True
    import asyncio
    try:
        import network
        wlan = network.WLAN(network.STA_IF)
    except Exception:
        _state = 'off'
        _started = False
        return
    try:
        if not wlan.active():
            wlan.active(True)
    except Exception:
        pass
    while True:
        try:
            if wlan.isconnected():
                _state = 'connected'
                await asyncio.sleep_ms(5000)
                continue
            saved = _saved()
            if not saved:
                _state = 'off'
                await asyncio.sleep_ms(8000)
                continue
            _state = 'connecting'
            ok = False
            for ssid, pw in saved:
                if wlan.isconnected():
                    ok = True
                    break
                try:
                    wlan.connect(ssid, pw)
                except Exception:
                    continue
                for _ in range(16):                 # ~8s, polled cooperatively
                    await asyncio.sleep_ms(500)
                    if wlan.isconnected():
                        ok = True
                        break
                if ok:
                    break
            _state = 'connected' if (ok or wlan.isconnected()) else 'off'
            if _state != 'connected':
                await asyncio.sleep_ms(10000)       # back off before retrying
        except Exception:
            _state = 'off'
            await asyncio.sleep_ms(8000)
