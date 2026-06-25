# Desc: Nova D1 LoRa messaging manager — background RX + send queue + shared inbox.
# File: /Packages/NovaD1/novamsg.py
#
# Owns the SX1276 (so the Messages app AND the web panel share ONE radio + ONE
# inbox). Background coroutine: listen, parse novamesh packets, dedup, drop into
# the inbox + fire a notification; drain a send queue (half-duplex: TX then back
# to RX). Pausable so the CC1101/SD tests can use the shared SPI bus.
# Verified: SX1276 inits on hardware (RegVersion 0x12). On-air RX needs a 2nd
# board. MicroPython-safe: no f-strings, .format() only.

_INBOX = []          # list of {ts, src, text, me?}
_OUTQ = []           # pending outgoing (dst, text)
_MAX = 30
_paused = False
_started = False
_lora = None
_msgid = 0


def _ts():
    try:
        import utime
        t = utime.localtime()
        return '{:02d}:{:02d}'.format(t[3], t[4])
    except Exception:
        return '--:--'


def inbox():
    return list(_INBOX)


def radio_ok():
    return _lora is not None


def pause():
    global _paused
    _paused = True


def resume():
    global _paused
    _paused = False


def send(text, dst=None):
    """Queue an outgoing message (broadcast by default). Echoed into the inbox."""
    import novamesh
    _OUTQ.append((novamesh.BROADCAST if dst is None else dst, str(text)[:120]))
    return True


async def manager():
    """Background service: own the radio, RX->inbox+notify, drain the send queue."""
    global _lora, _started, _msgid
    if _started:
        return
    _started = True
    import asyncio
    import novamesh
    seen = novamesh.Seen()
    try:
        import novalora
        lr = novalora.LoRa()
        if not lr.begin():
            _lora = None
            _started = False
            return
        lr.start_rx()
        _lora = lr
    except Exception:
        _lora = None
        _started = False
        return
    me = novamesh.node_id()
    while True:
        try:
            if _paused:
                await asyncio.sleep_ms(300)
                continue
            raw = _lora.poll()
            if raw:
                pkt = novamesh.parse_packet(raw)
                if pkt and pkt['src'] != me and seen.first_time(pkt['src'], pkt['id']):
                    try:
                        txt = pkt['payload'].decode('utf-8')
                    except Exception:
                        txt = '?'
                    _INBOX.append({'ts': _ts(), 'src': pkt['src'], 'text': txt})
                    if len(_INBOX) > _MAX:
                        _INBOX.pop(0)
                    try:
                        import novanotify
                        novanotify.notify('LoRa {}: {}'.format(pkt['src'], txt[:18]))
                    except Exception:
                        pass
            if _OUTQ:
                dst, text = _OUTQ.pop(0)
                _msgid = (_msgid + 1) & 0xFFFF
                try:
                    _lora.send(novamesh.make_packet(me, dst, _msgid, text))
                except Exception:
                    pass
                _INBOX.append({'ts': _ts(), 'src': me, 'text': text, 'me': True})
                if len(_INBOX) > _MAX:
                    _INBOX.pop(0)
                _lora.start_rx()
            await asyncio.sleep_ms(120)
        except Exception:
            await asyncio.sleep_ms(500)
