# pcap writer: libpcap global header + records round-trip (Wireshark-openable).
import sys
import os
import struct
import tempfile
import _shims
_shims.install()
from _shims import T
import novapcap as P

t = T('test_novapcap')

path = tempfile.mktemp(suffix='.pcap')
w = P.PcapWriter(path, linktype=P.LINKTYPE_IEEE802_11, snaplen=4096)
frames = [b'\x80\x00\x00\x00' + b'\xff' * 6 + b'BEACON', b'\x08\x01' + b'\xab' * 20, bytes(range(40))]
for i, fr in enumerate(frames):
    w.write(fr, ts_sec=1000 + i, ts_usec=i * 111)
w.close()

data = open(path, 'rb').read()
magic, vM, vm, tz, sig, snap, net = struct.unpack('<IHHiIII', data[:24])
t.eq(magic, 0xa1b2c3d4, 'pcap magic')
t.eq((vM, vm), (2, 4), 'pcap version 2.4')
t.eq((snap, net), (4096, 105), 'snaplen + linktype 802.11')
t.eq(w.count, 3, 'writer counted 3')

off = 24
got = []
while off < len(data):
    ts_s, ts_u, incl, orig = struct.unpack('<IIII', data[off:off + 16])
    off += 16
    got.append((ts_s, orig, data[off:off + incl]))
    off += incl
t.eq(len(got), 3, 'three records')
for i, (ts_s, orig, payload) in enumerate(got):
    t.ok(payload == frames[i] and ts_s == 1000 + i and orig == len(frames[i]), 'record %d round-trips' % i)

try:
    os.remove(path)
except OSError:
    pass
sys.exit(t.done())
