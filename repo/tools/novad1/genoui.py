#!/usr/bin/env python3
"""Generate novaoui.py — a compact MAC-prefix -> vendor table for the Nova D1.

Source: the IEEE MA-L registry (oui.csv from https://standards-oui.ieee.org/oui/).
The full registry is ~3.8 MB and ~40,000 assignments, which no microcontroller is
going to hold. This picks out the vendors that actually matter for identifying
what is on a network or in the air around you -- cameras, IoT silicon, phones,
smart-home hubs, network gear -- and emits them as a flat dict.

Everything in the generated table came from the registry, not from recall. A
prefix that is not in the table renders as the raw prefix with NO vendor claimed;
a wrong vendor label is worse than no label, especially on a device whose whole
job is telling you what something is.

Usage:
    python3 genoui.py oui.csv > ../../packages/novad1/novaoui.py
"""
import csv
import re
import sys

# Vendors worth carrying, and the device class to infer from them. The class is a
# HINT about what the silicon usually ends up in, never a claim about the specific
# device: an Espressif OUI means "an ESP32-class module", which could be a camera,
# a plug or a doorbell. The UI must say it that way.
#
# Each entry: (regex matched against the IEEE organisation name, short label, class)
WANTED = [
    # --- camera / video specifically -------------------------------------
    (r'^Hangzhou Hikvision', 'Hikvision', 'camera'),
    (r'^Zhejiang Dahua|^Dahua', 'Dahua', 'camera'),
    (r'^Axis Communications', 'Axis', 'camera'),
    (r'Amcrest', 'Amcrest', 'camera'),
    (r'^Reolink|Baichuan', 'Reolink', 'camera'),
    (r'^Wyze', 'Wyze', 'camera'),
    (r'^Arlo', 'Arlo', 'camera'),
    (r'^Ubiquiti', 'Ubiquiti', 'network'),
    (r'^Mobotix', 'Mobotix', 'camera'),
    (r'^Vivotek', 'Vivotek', 'camera'),
    (r'^Foscam|^Shenzhen Foscam', 'Foscam', 'camera'),
    (r'^Swann', 'Swann', 'camera'),
    (r'^Lorex', 'Lorex', 'camera'),
    (r'^Uniview|^Zhejiang Uniview', 'Uniview', 'camera'),
    (r'^GoPro', 'GoPro', 'camera'),
    (r'^Netatmo', 'Netatmo', 'camera'),
    (r'^Verkada', 'Verkada', 'camera'),
    (r'^Flock Safety', 'Flock Safety', 'camera'),

    # --- IoT silicon: what most cheap smart devices actually are ---------
    (r'^Espressif', 'Espressif', 'iot'),
    (r'^Realtek', 'Realtek', 'iot'),
    (r'^Tuya', 'Tuya', 'iot'),
    (r'^Shenzhen Bilian', 'Bilian', 'iot'),
    (r'^Beijing Xiaomi|^Xiaomi', 'Xiaomi', 'iot'),
    (r'^Shenzhen Yunni|^Tenda', 'Tenda', 'network'),
    (r'^Texas Instruments', 'TI', 'iot'),
    (r'^Nordic Semiconductor', 'Nordic', 'iot'),
    (r'^Silicon Laborator', 'Silabs', 'iot'),
    (r'^Murata', 'Murata', 'iot'),
    (r'^Raspberry Pi', 'Raspberry Pi', 'computer'),
    (r'^Seeed', 'Seeed', 'iot'),
    (r'^Particle Industries', 'Particle', 'iot'),

    # --- phones / personal ------------------------------------------------
    (r'^Apple, Inc', 'Apple', 'personal'),
    (r'^Samsung Electro|^Samsung Electronics', 'Samsung', 'personal'),
    (r'^Google, Inc|^Google LLC', 'Google', 'personal'),
    (r'^Motorola Mobility', 'Motorola', 'personal'),
    (r'^OnePlus', 'OnePlus', 'personal'),
    (r'^Huawei', 'Huawei', 'personal'),
    (r'^Fitbit', 'Fitbit', 'personal'),
    (r'^Garmin', 'Garmin', 'personal'),
    (r'^Sonos', 'Sonos', 'media'),
    (r'^Roku', 'Roku', 'media'),
    (r'^Amazon Technologies', 'Amazon', 'media'),
    (r'^Sony (Corporation|Interactive|Home)', 'Sony', 'media'),
    (r'^Nintendo', 'Nintendo', 'media'),
    (r'^Microsoft', 'Microsoft', 'media'),
    (r'^LG Electronics', 'LG', 'media'),
    (r'^Vizio', 'Vizio', 'media'),

    # --- network infrastructure ------------------------------------------
    (r'^NETGEAR', 'Netgear', 'network'),
    (r'^TP-LINK|^TP-Link', 'TP-Link', 'network'),
    (r'^ASUSTek', 'ASUS', 'network'),
    (r'^D-Link', 'D-Link', 'network'),
    (r'^Cisco Systems|^Cisco-Linksys|^Linksys', 'Cisco', 'network'),
    (r'^Belkin', 'Belkin', 'network'),
    (r'^ARRIS|^Arris', 'Arris', 'network'),
    (r'^Technicolor', 'Technicolor', 'network'),
    (r'^eero', 'eero', 'network'),
    (r'^MikroTik', 'MikroTik', 'network'),
    (r'^Aruba|^Hewlett Packard Enterprise', 'Aruba', 'network'),
    (r'^Ruckus', 'Ruckus', 'network'),
    (r'^Synology', 'Synology', 'nas'),
    (r'^QNAP', 'QNAP', 'nas'),
    (r'^Brother Industries', 'Brother', 'printer'),
    (r'^Seiko Epson', 'Epson', 'printer'),
    (r'^Canon', 'Canon', 'printer'),
    (r'^Hewlett Packard$|^HP Inc', 'HP', 'printer'),
    (r'^Intel Corporate', 'Intel', 'computer'),
    (r'^Dell Inc', 'Dell', 'computer'),
    (r'^Lenovo', 'Lenovo', 'computer'),
    (r'^VMware', 'VMware', 'computer'),
]

# A vendor with a huge number of assignments would bloat the table for no gain --
# cap each one and keep the lowest prefixes, which are the oldest and most common.
MAX_PER_VENDOR = 24


def build(path):
    compiled = [(re.compile(rx, re.I), label, klass) for rx, label, klass in WANTED]
    hits = {}
    total = 0
    with open(path, newline='', encoding='utf-8', errors='replace') as f:
        for row in csv.DictReader(f):
            if row.get('Registry') != 'MA-L':
                continue
            total += 1
            org = (row.get('Organization Name') or '').strip()
            asn = (row.get('Assignment') or '').strip().upper()
            if len(asn) != 6:
                continue
            for rx, label, klass in compiled:
                if rx.search(org):
                    hits.setdefault((label, klass), []).append(asn)
                    break
    return hits, total


def emit(hits, total, src):
    """Emit ONE sorted fixed-width string, not a dict.

    A dict of ~1000 entries costs roughly 50 KB of RAM the moment it is imported,
    which this device does not have to spare. The same data as a single string of
    8-character records (6 hex OUI + 2 hex vendor index) is ~8 KB as one object,
    and a binary search over it allocates nothing but a few small slices."""
    vendors = sorted({label for (label, _k) in hits})
    vidx = {v: i for i, v in enumerate(vendors)}
    klass = {}
    for (label, k) in hits:
        klass[label] = k

    recs = []
    for (label, _k), prefixes in hits.items():
        for pfx in sorted(prefixes)[:MAX_PER_VENDOR]:
            recs.append(pfx + '%02X' % vidx[label])
    recs.sort()

    out = []
    w = out.append
    w('# Desc: Nova D1 MAC-prefix -> vendor lookup (generated; do not hand-edit).')
    w('# File: /Packages/NovaD1/novaoui.py')
    w('#')
    w('# GENERATED by repo/tools/novad1/genoui.py from the IEEE MA-L registry')
    w('# (%s). Every prefix below came from that registry, not from recall:' % src)
    w('# %d of %d MA-L assignments, filtered to the vendors that matter for' % (len(recs), total))
    w('# identifying what is on a network or in the air around you.')
    w('#')
    w('# A prefix that is NOT here returns None and the caller shows the raw prefix')
    w('# with no vendor claimed. That is deliberate: on a tool whose whole job is')
    w('# telling you what something is, a wrong label is worse than no label.')
    w('#')
    w('# The class is a HINT about what the silicon usually ends up in, never a claim')
    w('# about a specific device -- an Espressif OUI means "an ESP32-class module",')
    w('# which might be a camera, a plug or a doorbell. Say it that way in the UI.')
    w('#')
    w('# Stored as ONE sorted string of 8-char records (6 hex OUI + 2 hex vendor')
    w('# index), binary-searched. As a dict this would cost ~50 KB of RAM on import;')
    w('# as a string it is ~%d bytes and lookup allocates almost nothing.' % (len(recs) * 8))
    w('# MicroPython-safe: no f-strings.')
    w('')
    w('VENDORS = (')
    for i in range(0, len(vendors), 4):
        w('    ' + ' '.join("'%s'," % v for v in vendors[i:i + 4]))
    w(')')
    w('')
    w('# vendor index -> device-class hint (same order as VENDORS)')
    w('CLASSES = (')
    cl = [klass[v] for v in vendors]
    for i in range(0, len(cl), 6):
        w('    ' + ' '.join("'%s'," % c for c in cl[i:i + 6]))
    w(')')
    w('')
    w('_T = (')
    CHUNK = 9          # records per source line
    for i in range(0, len(recs), CHUNK):
        w("    '" + ''.join(recs[i:i + CHUNK]) + "'")
    w(')')
    w('')
    w('_REC = 8')
    w('')
    w('')
    w('def _index(prefix):')
    w('    """Binary search the packed table. `prefix` is 6 upper-case hex chars."""')
    w('    lo = 0')
    w('    hi = len(_T) // _REC - 1')
    w('    while lo <= hi:')
    w('        mid = (lo + hi) // 2')
    w('        at = mid * _REC')
    w('        key = _T[at:at + 6]')
    w('        if key == prefix:')
    w('            return int(_T[at + 6:at + 8], 16)')
    w('        if key < prefix:')
    w('            lo = mid + 1')
    w('        else:')
    w('            hi = mid - 1')
    w('    return None')
    w('')
    w('')
    w('def lookup(mac):')
    w('    """(vendor, class) for a MAC, or (None, None) when nothing is known.')
    w('')
    w('    Accepts \'aa:bb:cc:dd:ee:ff\', \'AABBCCDDEEFF\' or raw bytes. A')
    w('    locally-administered address (bit 1 of the first octet) is RANDOMISED and')
    w('    has no vendor at all -- phones and modern laptops do this by default --')
    w('    so it returns (None, \'random\') rather than looking anything up. Reporting')
    w('    a manufacturer for a randomised MAC would be inventing one.')
    w('    """')
    w('    if isinstance(mac, (bytes, bytearray)):')
    w("        hexs = ''.join('{:02X}'.format(b) for b in mac)")
    w('    else:')
    w("        hexs = str(mac).replace(':', '').replace('-', '').upper()")
    w('    if len(hexs) < 6:')
    w('        return None, None')
    w('    try:')
    w('        first = int(hexs[0:2], 16)')
    w('    except Exception:')
    w('        return None, None')
    w('    if first & 0x02:')
    w("        return None, 'random'")
    w('    i = _index(hexs[0:6])')
    w('    if i is None:')
    w('        return None, None')
    w('    return VENDORS[i], CLASSES[i]')
    w('')
    w('')
    w('def prefix(mac):')
    w('    """The OUI as AA:BB:CC, for showing when no vendor is known."""')
    w('    if isinstance(mac, (bytes, bytearray)):')
    w("        hexs = ''.join('{:02X}'.format(b) for b in mac)")
    w('    else:')
    w("        hexs = str(mac).replace(':', '').replace('-', '').upper()")
    w("    return ':'.join((hexs[0:2], hexs[2:4], hexs[4:6])) if len(hexs) >= 6 else '?'")
    w('')
    return '\n'.join(out)


if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else 'oui.csv'
    hits, total = build(src)
    text = emit(hits, total, 'oui.csv')
    sys.stdout.write(text)
    sys.stderr.write('%d vendors, %d prefixes, from %d MA-L assignments (%d bytes)\n'
                     % (len(hits), sum(min(len(v), MAX_PER_VENDOR)
                                       for v in hits.values()), total, len(text)))
