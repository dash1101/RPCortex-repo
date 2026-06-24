# Desc: Nova D1 event log — small capped log on flash (works without an SD card).
# File: /Packages/NovaD1/novalog.py
#
# Logs EVENTS, not noise (boot, checks, crashes, errors, test results) — never
# per-frame, since each flash write is ~10ms on LittleFS and would stutter the
# loop. Capped ring (rewrites the file, keeping the last _MAX lines). Lives on
# flash under the OS root so boot-time events log before any SD is mounted.
# MicroPython-safe: no f-strings.

_LOGF = '/Vela/Logs/nova.log'
_MAX = 60


def _ts():
    try:
        import utime
        t = utime.localtime()
        return '{:02d}:{:02d}:{:02d}'.format(t[3], t[4], t[5])
    except Exception:
        return '--:--:--'


def tail(n=_MAX):
    try:
        with open(_LOGF) as f:
            lines = [l for l in f.read().split('\n') if l]
        return lines[-n:]
    except Exception:
        return []


def log(msg):
    try:
        lines = tail(_MAX - 1)
        lines.append(_ts() + ' ' + str(msg))
        try:
            with open(_LOGF, 'w') as f:
                f.write('\n'.join(lines) + '\n')
        except OSError:
            # /Vela/Logs may not exist yet — try to create it once
            try:
                import uos
                try:
                    uos.mkdir('/Vela')
                except OSError:
                    pass
                try:
                    uos.mkdir('/Vela/Logs')
                except OSError:
                    pass
                with open(_LOGF, 'w') as f:
                    f.write('\n'.join(lines) + '\n')
            except Exception:
                pass
    except Exception:
        pass


def clear():
    try:
        with open(_LOGF, 'w') as f:
            f.write('')
    except Exception:
        pass
