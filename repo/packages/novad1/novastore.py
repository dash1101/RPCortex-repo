# Desc: Nova D1 code store — save/load protocol codes to files, back up to SD.
# File: /Packages/NovaD1/novastore.py
#
# Codes (IR / sub-GHz / LoRa payloads / NFC) live as small text files under
# /Vela/nova/codes/<category>/ on FLASH (16 MB, instant, no SPI contention with the
# radios). A background mover copies them to /sd/nova/codes/ as a backup when the
# SD is free — briefly mounting (RF paused) so it never fights a radio mid-transmit.
# A transient save icon shows while a backup is pending. Flash stays the working
# copy, so reads never need the SD. MicroPython-safe: no f-strings.

_FLASH = '/Vela/nova/codes'
_SD = '/sd/nova/codes'
_QUEUE = []          # [(cat, name)] pending SD backup
_saving = False


def _mkdirs(path):
    import uos
    parts = path.split('/')
    cur = ''
    for p in parts:
        if not p:
            continue
        cur += '/' + p
        try:
            uos.mkdir(cur)
        except OSError:
            pass


def codes_dir(cat):
    d = _FLASH + '/' + cat
    _mkdirs(d)
    return d


def list_codes(cat):
    import uos
    try:
        return sorted(uos.listdir(codes_dir(cat)))
    except Exception:
        return []


def read_code(cat, name):
    try:
        with open(codes_dir(cat) + '/' + name) as f:
            return f.read()
    except Exception:
        return None


def save_code(cat, name, text):
    """Write the code to flash NOW (instant), queue an SD backup. Returns the path."""
    global _saving
    d = codes_dir(cat)
    path = d + '/' + name
    with open(path, 'w') as f:
        f.write(text)
    _QUEUE.append((cat, name))
    _saving = True
    return path


def delete_code(cat, name):
    import uos
    ok = False
    try:
        uos.remove(codes_dir(cat) + '/' + name)
        ok = True
    except Exception:
        pass
    return ok


def saving():
    return _saving


async def backup_mover():
    """Background: copy queued flash codes to the SD as backup, then clear the icon.
    Best-effort — if there's no SD, the flash copy is still the working store."""
    import asyncio
    global _saving
    while True:
        if _QUEUE:
            try:
                import novamsg
                novamsg.pause()                  # free the shared SPI bus
            except Exception:
                pass
            try:
                import sdmgr
                okk, _m = sdmgr.mount()
                if okk:
                    while _QUEUE:
                        cat, name = _QUEUE[0]
                        try:
                            _mkdirs(_SD + '/' + cat)
                            data = read_code(cat, name)
                            if data is not None:
                                with open(_SD + '/' + cat + '/' + name, 'w') as f:
                                    f.write(data)
                        except Exception:
                            pass
                        _QUEUE.pop(0)
                    try:
                        sdmgr.unmount()           # free the bus again for the radios
                    except Exception:
                        pass
                else:
                    _QUEUE[:] = []                # no SD — flash copy is enough
            except Exception:
                _QUEUE[:] = []
            try:
                import novamsg
                novamsg.resume()
            except Exception:
                pass
            _saving = bool(_QUEUE)
        await asyncio.sleep_ms(2000)
