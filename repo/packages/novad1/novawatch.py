# Desc: Nova D1 radio observer — who is around, since when, and coming or going.
# File: /Packages/NovaD1/novawatch.py
#
# A scan button tells you what is nearby right now. This keeps watching in the
# BACKGROUND and remembers, which is what turns a list of MACs into something you
# can reason about: how long that device has been here, whether its signal is
# rising, whether it followed you, whether the phone that means "someone is home"
# just arrived.
#
# That last one is the same trick a WiFi camera uses to know you are home — it
# watches for a radio it recognises. Nothing is transmitted to do it and nothing
# is joined; it is passive listening only.
#
# WHAT THE RADIO CAN ACTUALLY SEE (the ceiling, so it is not re-litigated):
#   WLAN.scan()  ACCESS POINTS ONLY. MicroPython has no monitor mode on the
#                CYW43, so client devices, probe requests and deauths are simply
#                not visible. A phone is invisible here unless it is hotspotting.
#   BLE gap_scan EVERY advertising device, with its full payload. This is the rich
#                channel: phones, watches, earbuds, trackers, TVs, smart-home gear.
#
# The registry and all the analysis are pure logic (host-testable); only the two
# scan calls touch hardware. MicroPython-safe: no f-strings, .format() only.

from novacore import reg as _reg, save_reg as _save_reg

MAX_DEVICES = 64        # hard cap — the weakest, stalest entry is dropped first
GONE_MS = 90000         # not seen this long => departed
_HYST = 2               # consecutive misses before calling something departed

_SEEN = {}              # mac -> record
_EVENTS = []            # (kind, mac, label) awaiting collection
_MAX_EVENTS = 20
_started = False


def _now():
    try:
        import utime
        return utime.ticks_ms()
    except Exception:
        return 0


def _elapsed(a, b):
    try:
        import utime
        return utime.ticks_diff(a, b)
    except Exception:
        return a - b


# --------------------------------------------------------------- the registry
def observe(entries, kind='ble', now=None):
    """Fold one scan pass into the registry. Returns the list of NEW macs.

    `entries` are dicts with at least 'mac' and 'rssi'; BLE entries may carry
    'adv' (the raw advertisement) and 'name', WiFi entries 'ssid' and 'channel'.
    """
    now = _now() if now is None else now
    new = []
    for e in entries or ():
        # Tolerate junk. This runs unattended in the background, so one malformed
        # entry from a radio driver must not take the observer down with it.
        try:
            mac = e.get('mac') or e.get('bssid')
        except Exception:
            continue
        if not mac:
            continue
        mac = mac.lower()
        # rssi may legitimately be None: an AP association table carries no
        # signal strength, and inventing a plausible number would be making data
        # up. None flows through and the UI renders it as 'joined'.
        rssi = e.get('rssi', -100)
        rec = _SEEN.get(mac)
        if rec is None:
            rec = {
                'mac': mac, 'kind': kind, 'first': now, 'count': 0,
                'best': rssi, 'name': e.get('name') or e.get('ssid') or '',
                'vendor': None, 'class': None, 'ssid': e.get('ssid', ''),
                'channel': e.get('channel'), 'misses': 0, 'rssi': rssi,
                'trend': 0,
            }
            _identify(rec, e)
            _SEEN[mac] = rec
            new.append(mac)
            _emit('new', mac, rec)
        else:
            if rssi is not None and rec.get('rssi') is not None:
                rec['trend'] = rssi - rec['rssi']
            if not rec['name']:
                rec['name'] = e.get('name') or e.get('ssid') or ''
        rec['rssi'] = rssi
        rec['last'] = now
        rec['count'] += 1
        rec['misses'] = 0
        if rssi is not None and (rec['best'] is None or rssi > rec['best']):
            rec['best'] = rssi
    _sweep(now)
    _prune()
    return new


def _identify(rec, entry):
    """Attach vendor + device class. Both modules are imported lazily so a device
    that never opens this app does not pay for the OUI table."""
    try:
        import novaoui
        v, c = novaoui.lookup(rec['mac'])
        rec['vendor'] = v
        rec['class'] = c
        rec['random'] = (c == 'random')
    except Exception:
        rec['random'] = False
    adv = entry.get('adv')
    if adv:
        try:
            import novableid
            info = novableid.identify(rec['mac'], adv, rec.get('name', ''))
            rec['vendor'] = info.get('vendor') or rec.get('vendor')
            rec['class'] = info.get('kind') or rec.get('class')
            rec['name'] = info.get('name') or rec.get('name', '')
            rec['tx'] = info.get('tx')
            rec['random'] = info.get('random', rec.get('random', False))
        except Exception:
            pass


def _sweep(now):
    """Mark anything not heard from recently as departed, with hysteresis — a
    single missed scan is normal (BLE advertising is bursty and a device can be
    behind a wall for one pass), so one miss must not fire a departure."""
    labels = known()
    for mac, rec in _SEEN.items():
        if _elapsed(now, rec.get('last', now)) < GONE_MS:
            continue
        rec['misses'] += 1
        if rec['misses'] == _HYST and not rec.get('gone'):
            rec['gone'] = True
            if mac in labels:
                _emit('left', mac, rec)


def _prune():
    """Cap the table. Weakest-and-stalest goes first, but a device you have
    TAGGED is never dropped — the whole point of tagging it is that you care."""
    if len(_SEEN) <= MAX_DEVICES:
        return
    labels = known()
    drop = sorted((r for m, r in _SEEN.items() if m not in labels),
                  key=lambda r: (r.get('last', 0), r.get('rssi', -120)))
    for rec in drop[:len(_SEEN) - MAX_DEVICES]:
        _SEEN.pop(rec['mac'], None)


def devices(sort='rssi', kind=None):
    """Everything currently known, strongest first by default."""
    out = [r for r in _SEEN.values() if kind is None or r.get('kind') == kind]
    if sort == 'rssi':
        # A None signal (a joined AP client) sorts to the bottom rather than
        # raising — Python will not order None against an int.
        out.sort(key=lambda r: (r.get('rssi') if r.get('rssi') is not None
                                else -121), reverse=True)
    elif sort == 'first':
        out.sort(key=lambda r: r.get('first', 0))
    elif sort == 'name':
        out.sort(key=lambda r: (r.get('name') or '~').lower())
    return out


def get(mac):
    return _SEEN.get((mac or '').lower())


def count():
    return len(_SEEN)


def clear():
    _SEEN.clear()
    del _EVENTS[:]


# ------------------------------------------------------------------ presence
def known():
    """Tagged devices: mac -> your label. Persisted, so it survives a reboot."""
    raw = _reg('Apps.NovaD1_Known', '') or ''
    out = {}
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        bits = part.split('|', 1)
        if bits[0]:
            out[bits[0].strip().lower()] = (bits[1].strip() if len(bits) > 1
                                            else bits[0].strip())
    return out


def tag(mac, label):
    """Name a device so its arrivals and departures are reported."""
    mac = (mac or '').lower()
    if not mac:
        return False
    k = known()
    k[mac] = (label or mac)[:14].replace(',', ' ').replace('|', ' ')
    return _save_reg('Apps.NovaD1_Known',
                     ','.join('{}|{}'.format(m, l) for m, l in k.items()))


def untag(mac):
    k = known()
    k.pop((mac or '').lower(), None)
    return _save_reg('Apps.NovaD1_Known',
                     ','.join('{}|{}'.format(m, l) for m, l in k.items()))


def presence():
    """(label, mac, present, rssi) for every tagged device — the "is anyone home"
    view. A tagged device that has never been seen still appears, as absent."""
    out = []
    for mac, label in sorted(known().items(), key=lambda kv: kv[1].lower()):
        rec = _SEEN.get(mac)
        here = bool(rec) and not rec.get('gone')
        out.append((label, mac, here, rec.get('rssi') if rec else None))
    return out


# -------------------------------------------------------------------- events
def _emit(kind, mac, rec):
    label = known().get(mac)
    if kind == 'new' and label:
        kind = 'arrived'
    if kind == 'new' and not _reg_on('Apps.NovaD1_Watch_New', 'off'):
        return                       # unknown-device alerts are opt-in: noisy
    _EVENTS.append((kind, mac, label or rec.get('name') or mac))
    if len(_EVENTS) > _MAX_EVENTS:
        _EVENTS.pop(0)


def _reg_on(key, default):
    return str(_reg(key, default)).lower() in ('on', 'true', '1')


def silenced():
    """True when the radios are locked down and nothing may listen.

    Checked between every phase of the observer, not once per cycle: engaging
    incognito must stop the CURRENT pass, not the one after it."""
    try:
        import novastealth
        return novastealth.blocked()
    except Exception:
        pass
    try:
        import RPCortex as _R
        return _R.radio_locked()
    except Exception:
        return False


def events(clear_after=True):
    """Collect anything that happened since the last call."""
    out = list(_EVENTS)
    if clear_after:
        del _EVENTS[:]
    return out


# ------------------------------------------------------------- the locator
class Tracker:
    """Turns a stream of RSSI samples into a hot/colder reading you can walk with.

    RSSI from a single antenna cannot give a direction — only a distance-ish
    magnitude that rises as you close in. So this reports LEVEL and TREND and
    lets you do the triangulating by walking, which is how every practical
    single-antenna locator works. It deliberately does not draw an arrow, because
    it does not know one."""
    def __init__(self, mac, tx=None):
        self.mac = (mac or '').lower()
        self.tx = tx                 # advertised TX power, when the device gave one
        self.level = None            # smoothed RSSI
        self.best = -120
        self.trend = 0
        self.samples = 0

    def feed(self, rssi):
        if rssi is None:
            return self.level
        self.samples += 1
        if self.level is None:
            self.level = float(rssi)
        else:
            prev = self.level
            # EWMA: raw RSSI jitters several dB between packets, and an unsmoothed
            # readout flickers too much to walk with.
            self.level = self.level * 0.7 + rssi * 0.3
            self.trend = self.level - prev
        if rssi > self.best:
            self.best = rssi
        return self.level

    def bars(self, n=10):
        """0..n, for a meter. -30 dBm is on top of it, -95 is the far edge."""
        if self.level is None:
            return 0
        frac = (self.level + 95.0) / 65.0
        frac = 0.0 if frac < 0 else (1.0 if frac > 1 else frac)
        return int(frac * n + 0.5)

    def hint(self):
        """The word a person actually needs while walking around."""
        if self.level is None:
            return 'listening'
        if self.samples > 2:
            if self.trend > 1.2:
                return 'warmer'
            if self.trend < -1.2:
                return 'colder'
        if self.level > -45:
            return 'very close'
        if self.level > -60:
            return 'close'
        if self.level > -75:
            return 'nearby'
        return 'far'

    # Free-space path loss at 1 m and 2.44 GHz is 20*log10(1) + 20*log10(f) -
    # 147.55 = 40.2 dB, so a device advertising P dBm reads about P - 40 dBm at
    # one metre. That one-metre reference is what the path-loss model needs;
    # feeding it the raw advertised power instead put a strong signal at 90 m.
    _REF_1M = 40.2
    _PATH_N = 2.5          # path-loss exponent; ~2 outdoors, 2.5-4 indoors

    def metres(self):
        """A very rough distance, or None when the device advertised no TX power.

        Log-distance path loss. Walls, bodies and antenna orientation each move
        this by metres, so it is an order of magnitude and never a measurement —
        which is why the locator leads with warmer/colder instead."""
        if self.level is None or self.tx is None:
            return None
        try:
            ref = self.tx - self._REF_1M                 # expected RSSI at 1 m
            d = 10 ** ((ref - self.level) / (10.0 * self._PATH_N))
            return round(d, 1) if d < 100 else None      # beyond this it is noise
        except Exception:
            return None


# -------------------------------------------------- the background observer
def started():
    return _started


async def observer():
    """Background service: keep listening, so the picture builds while you use
    the device for something else.

    Alternates BLE and WiFi with a rest in between rather than scanning flat out
    — a continuous scan would hold the radio permanently, block WiFi from
    connecting, and drain the battery for no extra information. Every wait is an
    await, so the UI stays responsive throughout.
    """
    global _started
    if _started:
        return
    _started = True
    import asyncio
    while True:
        try:
            if not _reg_on('Apps.NovaD1_Watch', 'on'):
                await asyncio.sleep_ms(4000)
                continue
            if silenced():
                await asyncio.sleep_ms(4000)
                continue

            try:
                import novable
                res = None
                for res in novable.scan_steps(3000):
                    await asyncio.sleep_ms(50)
                if res:
                    observe(res, 'ble')
            except Exception:
                pass
            await asyncio.sleep_ms(500)
            if silenced():
                continue

            # WiFi only every few passes: an AP scan takes the STA interface for
            # a second or two, and doing it constantly fights the connect loop.
            try:
                import novawifi
                if novawifi.state() != 'connecting':
                    import novawardrive
                    aps = novawardrive.scan_now()
                    if aps:
                        observe(aps, 'wifi')
            except Exception:
                pass

            if silenced():
                continue
            try:                              # clients joined to our own AP
                sta = ap_stations()
                if sta:
                    observe(sta, 'client')
            except Exception:
                pass

            _notify_events()
            await asyncio.sleep_ms(int(_reg('Apps.NovaD1_Watch_Period', 8000)))
        except Exception:
            await asyncio.sleep_ms(8000)


def ap_stations():
    """MACs of devices joined to OUR OWN access point, if one is running.

    This is the one way WiFi shows client devices without monitor mode: the CYW43
    driver exposes the association table of an AP we are hosting
    (WLAN(AP_IF).status('stations'), up to 32 entries). It is not passive — a
    device has to actually join — but for "is my phone home", having the phone
    auto-join the Nova D1's network is a perfectly good way to be told.

    Everything else about client devices really does need monitor mode, which
    this radio does not have under MicroPython.
    """
    out = []
    if silenced():
        return out
    try:
        import network
        ap = network.WLAN(network.AP_IF)
        if not ap.active():
            return out
        for st in ap.status('stations') or ():
            mac = st[0] if isinstance(st, (tuple, list)) else st
            out.append({
                'mac': ':'.join('{:02x}'.format(b) for b in mac),
                # An association table has no signal strength in it. Reporting a
                # plausible-looking number would be inventing data, so joined
                # clients carry a sentinel the UI shows as 'joined'.
                'rssi': None,
            })
    except Exception:
        pass
    return out


def _notify_events():
    """Turn arrivals/departures into notifications, if the user asked for them."""
    if not _reg_on('Apps.NovaD1_Watch_Notify', 'on'):
        events()                      # drain so they don't pile up
        return
    for kind, _mac, label in events():
        if kind not in ('arrived', 'left'):
            continue
        try:
            import novanotify
            novanotify.notify('{} {}'.format(label, kind))
        except Exception:
            pass
