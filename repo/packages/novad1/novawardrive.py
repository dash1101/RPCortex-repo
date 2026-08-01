# Desc: Nova D1 wardriving — WiFi survey to a WiGLE-compatible CSV.
# File: /Packages/NovaD1/novawardrive.py
#
# Scan-based, NOT packet capture: logs each access point's BSSID / SSID / channel /
# RSSI / encryption, tagged with GPS position + time, deduped by BSSID, appended to a
# WiGLE-1.4 CSV. Needs only WLAN.scan() (no monitor mode / pcap — that's D2). Logs to
# the SD card when present, else onboard flash; on flash it respects the storage guard
# (warn ~95%, hard-stop ~98%) so a survey can't fill the disk.
#
# The parsing + CSV + dedup are pure logic (CPython-testable); the radio + GPS reads
# are isolated. MicroPython-safe: no f-strings, positional split, .format() only.

_SEC = {0: 'OPEN', 1: 'WEP', 2: 'WPA-PSK', 3: 'WPA2-PSK',
        4: 'WPA/WPA2-PSK', 5: 'WPA2-ENT'}


def sec_str(sec):
    """WiGLE-ish auth string for a scan security code."""
    return _SEC.get(sec, 'WPA?')


def bssid_hex(b):
    """bytes -> AA:BB:CC:DD:EE:FF (lower-case, colon-separated)."""
    try:
        return ':'.join('{:02x}'.format(x) for x in b)
    except Exception:
        return str(b)


def parse_scan(raw):
    """Turn WLAN.scan() tuples into AP dicts. A scan tuple is
    (ssid, bssid, channel, RSSI, security, hidden). Tolerant of str/bytes ssid."""
    out = []
    for e in raw or ():
        try:
            ssid = e[0]
            if isinstance(ssid, (bytes, bytearray)):
                ssid = ssid.decode('utf-8')
        except Exception:
            ssid = ''
        try:
            out.append({
                'bssid': bssid_hex(e[1]),
                'ssid': ssid,
                'channel': e[2],
                'rssi': e[3],
                'sec': e[4],
            })
        except Exception:
            pass
    return out


def scan_now():
    """Run one WiFi scan on the STA interface; return parsed APs (or [])."""
    # Incognito latch: refuse while stealth is engaged. Killing the radio isn't
    # enough by itself — this call would just re-activate it.
    try:
        import novastealth
        if novastealth.blocked():
            return []
    except Exception:
        pass
    try:
        import network
        w = network.WLAN(network.STA_IF)
        if not w.active():
            w.active(True)
        return parse_scan(w.scan())
    except Exception:
        return []


def wigle_header(model='NovaD1'):
    """The two WiGLE-1.4 header lines (pre-amble + column names)."""
    pre = ('WigleWifi-1.4,appRelease=novad1,model={},release=1.0,'
           'device=NovaD1,display=,board=rp2350,brand=NovaLabs').format(model)
    cols = ('MAC,SSID,AuthMode,FirstSeen,Channel,RSSI,CurrentLatitude,'
            'CurrentLongitude,AltitudeMeters,AccuracyMeters,Type')
    return pre + '\n' + cols + '\n'


def _csv_field(s):
    """Escape a CSV field (SSIDs can contain commas/quotes)."""
    s = str(s)
    if ',' in s or '"' in s or '\n' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def wigle_row(ap, ts, lat=None, lon=None, alt=None):
    """One WiGLE CSV data row for an AP. lat/lon/alt blank when there's no fix."""
    return ','.join((
        ap['bssid'],
        _csv_field(ap.get('ssid', '')),
        '[{}]'.format(sec_str(ap.get('sec', -1))),
        ts,
        str(ap.get('channel', '')),
        str(ap.get('rssi', '')),
        '' if lat is None else '{:.6f}'.format(lat),
        '' if lon is None else '{:.6f}'.format(lon),
        '' if alt is None else str(alt),
        '',                     # accuracy — unknown
        'WIFI',
    )) + '\n'


class Session:
    """Accumulates unique APs (by BSSID) and formats WiGLE rows. Pure — the caller
    feeds it scan results + a GPS fix and writes rows() somewhere."""
    def __init__(self):
        self.seen = set()
        self.total = 0        # unique APs
        self.scans = 0        # scan passes

    def add(self, aps, ts, lat=None, lon=None, alt=None):
        """Add a scan pass; return the CSV rows for APs not seen before."""
        self.scans += 1
        rows = []
        for ap in aps:
            b = ap.get('bssid')
            if not b or b in self.seen:
                continue
            self.seen.add(b)
            self.total += 1
            rows.append(wigle_row(ap, ts, lat, lon, alt))
        return rows


def log_dir():
    """Where the CSV goes: the SD card if mounted (recommended for wardriving —
    lots of writes), else onboard flash."""
    try:
        import sdmgr
        if sdmgr.is_mounted():
            return '/sd/nova', True
    except Exception:
        pass
    return '/Vela/nova', False


def can_write(on_sd):
    """(ok, message). SD writes are always fine. Flash writes respect the storage
    guard: refuse at the block level, warn near it."""
    if on_sd:
        return True, ''
    try:
        from RPCortex import storage_state
        pct, level = storage_state('/')
    except Exception:
        return True, ''
    if level == 'block':
        return False, 'Flash {}% full - stopping (free space or use an SD card).'.format(pct)
    if level == 'warn':
        return True, 'Flash {}% full - low; an SD card is recommended.'.format(pct)
    return True, ''
