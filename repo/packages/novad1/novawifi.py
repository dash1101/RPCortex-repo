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
_paused = False           # set while a foreground scan owns the STA interface
_synced = False           # NTP-on-first-connect one-shot


def state():
    return _state


def pause():
    """Pause the connect loop so a foreground WLAN.scan() can run uncontended."""
    global _paused
    _paused = True


def resume():
    global _paused
    _paused = False


def _saved():
    try:
        import net
        return net._read_networks() or []
    except Exception:
        return []


async def _sync_clock():
    """Step the NTP sync, awaiting between every step.

    This used to be a bare `novartc.online_sync()` call — a SYNCHRONOUS blocking
    function invoked from inside this coroutine without an await. DNS plus a recv
    with a multi-second timeout stalled the whole event loop, and the GUI runs on
    that loop, so the device locked up on first WiFi connect. That is the reported
    'ntp sync freezes the OS'. Driving the generator and awaiting between steps is
    the fix; the sync path stays available for callers that aren't on the loop."""
    import asyncio
    try:
        import novartc
        for _st in novartc.sync_steps():
            await asyncio.sleep_ms(0)           # hand the loop back between steps
    except Exception:
        pass


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
            # Incognito: never re-associate while stealth is engaged. Without this
            # the manager brings the radio straight back up after the kill.
            try:
                import novastealth
                if novastealth.blocked():
                    if _state != 'off':
                        _state = 'off'
                    await asyncio.sleep_ms(1000)
                    continue
            except Exception:
                pass
            if _paused:                         # a scan owns the interface — wait
                await asyncio.sleep_ms(400)
                continue
            if wlan.isconnected():
                if _state != 'connected':
                    _state = 'connected'
                    global _synced
                    if not _synced:             # one-shot NTP sync on first connect
                        _synced = True
                        await _sync_clock()
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
