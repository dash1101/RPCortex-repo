# Desc: Nova D1 pcap writer — capture 802.11 frames to a Wireshark-readable file.
# File: /Packages/NovaD1/novapcap.py
#
# Writes the classic libpcap format (the .pcap Wireshark opens): a 24-byte global
# header, then for each frame a 16-byte record header + the raw bytes. This is the
# pure-software half of "WiFi pcap support" and is firmware-INDEPENDENT — it works
# the moment SOMETHING hands it frames. Two frame sources are possible on the D1:
#   * a custom firmware with esp_wifi promiscuous mode (real 802.11 sniffing), or
#   * any bytes you already have (e.g. ESP-NOW payloads, replayed captures).
# Stock MicroPython has no promiscuous API (see `novad1 wifiprobe`), so true
# sniffing waits on a custom firmware C module — but the writer is ready now and
# is verified byte-for-byte against the libpcap spec.
#
# MicroPython-safe: no f-strings, positional split, .format() only, ustruct.

try:
    import ustruct as struct
except ImportError:
    import struct

_MAGIC = 0xa1b2c3d4                 # microsecond-resolution, little-endian

# DLT / LINKTYPE values Wireshark understands for WiFi frames:
LINKTYPE_IEEE802_11 = 105           # bare 802.11 MAC frames (no radio header)
LINKTYPE_RADIOTAP = 127             # 802.11 with a radiotap header (RSSI/channel)
LINKTYPE_ETHERNET = 1               # for completeness


def _nova_base():
    # Mirror novastore's root choice without importing it (keep this standalone).
    try:
        import uos
        try:
            uos.stat('/sd/nova')
            return '/sd/nova'
        except OSError:
            pass
    except Exception:
        pass
    return '/Vela/nova'


def captures_dir():
    base = _nova_base() + '/captures'
    try:
        import uos
        for part in ('/Vela/nova', '/sd/nova', base):
            try:
                uos.mkdir(part)
            except OSError:
                pass            # exists or parent handled below
    except Exception:
        pass
    return base


class PcapWriter:
    """Streams frames to a .pcap file. Use as: w = PcapWriter(path); w.write(frame);
    ... w.close(). Streams straight to flash/SD — never buffers the whole capture in
    RAM. snaplen caps how many bytes of each frame are stored (the rest is recorded
    in the original-length field so Wireshark shows it was truncated)."""

    def __init__(self, path, linktype=LINKTYPE_IEEE802_11, snaplen=4096):
        self.path = path
        self.snaplen = snaplen
        self.count = 0
        self.f = open(path, 'wb')
        # global header: magic, ver_major, ver_minor, thiszone(i32), sigfigs,
        # snaplen, network(linktype) — 24 bytes, little-endian.
        self.f.write(struct.pack('<IHHiIII', _MAGIC, 2, 4, 0, 0, snaplen, linktype))

    def write(self, data, ts_sec=None, ts_usec=0):
        if ts_sec is None:
            try:
                import utime
                ts_sec = utime.time()
                ts_usec = (utime.ticks_us() % 1000000)
            except Exception:
                ts_sec = 0
                ts_usec = 0
        n = len(data)
        incl = n if n <= self.snaplen else self.snaplen
        # record header: ts_sec, ts_usec, incl_len, orig_len — 16 bytes.
        self.f.write(struct.pack('<IIII', ts_sec & 0xffffffff, ts_usec & 0xffffffff, incl, n))
        self.f.write(data if incl == n else data[:incl])
        self.count += 1

    def flush(self):
        try:
            self.f.flush()
        except Exception:
            pass

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


def open_capture(name='capture', linktype=LINKTYPE_IEEE802_11, snaplen=4096):
    """Open a timestamped capture under the captures dir. Returns a PcapWriter."""
    d = captures_dir()
    try:
        import utime
        stamp = utime.time()
    except Exception:
        stamp = 0
    path = d + '/' + name + '_' + str(stamp) + '.pcap'
    return PcapWriter(path, linktype, snaplen)
