# Desc: Nova D1 mesh packet layer — addressing, IDs, ttl, serialize/dedup.
# File: /Packages/NovaD1/novamesh.py
#
# Pure logic (no radio, no hardware) so it's CPython-testable — the foundation for
# Meshtastic-style P2P over LoRa. The radio (novalora) just carries these bytes.
# Frame:  MAGIC(1) VER(1) SRC(2) DST(2) ID(2) TTL(1) LEN(1) PAYLOAD(LEN) CRC(1)
#   DST 0xFFFF = broadcast.  CRC = sum of all prior bytes & 0xFF (link integrity;
#   LoRa already CRCs on-air — this catches framing). Dedup by (src,id) ring so a
#   re-broadcast (mesh forward) isn't processed twice. MicroPython-safe.

_MAGIC = 0x4E        # 'N'
_VER = 1
BROADCAST = 0xFFFF
_HDR = 10            # bytes before payload


def node_id():
    """A stable 16-bit node id: Apps.NovaD1_NodeID, else from machine.unique_id."""
    try:
        import regedit
        v = regedit.read('Apps.NovaD1_NodeID')
        if v:
            return int(v) & 0xFFFF
    except Exception:
        pass
    try:
        import machine
        u = machine.unique_id()
        return ((u[-1] << 8) | u[-2]) & 0xFFFF if len(u) >= 2 else (u[0] & 0xFFFF)
    except Exception:
        return 0x0001


def make_packet(src, dst, msg_id, payload, ttl=3):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    payload = payload[:200]
    body = bytes([_MAGIC, _VER,
                  (src >> 8) & 0xFF, src & 0xFF,
                  (dst >> 8) & 0xFF, dst & 0xFF,
                  (msg_id >> 8) & 0xFF, msg_id & 0xFF,
                  ttl & 0xFF, len(payload) & 0xFF]) + payload
    crc = 0
    for b in body:
        crc = (crc + b) & 0xFF
    return body + bytes([crc])


def parse_packet(data):
    if data is None or len(data) < _HDR + 1:
        return None
    if data[0] != _MAGIC or data[1] != _VER:
        return None
    plen = data[9]
    if len(data) < _HDR + plen + 1:
        return None
    crc = 0
    for i in range(_HDR + plen):
        crc = (crc + data[i]) & 0xFF
    if crc != data[_HDR + plen]:
        return None
    return {
        'src': (data[2] << 8) | data[3],
        'dst': (data[4] << 8) | data[5],
        'id': (data[6] << 8) | data[7],
        'ttl': data[8],
        'payload': bytes(data[_HDR:_HDR + plen]),
    }


class Seen:
    """Bounded (src,id) dedup ring — True the FIRST time a key is seen."""
    def __init__(self, cap=64):
        self._cap = cap
        self._q = []
        self._s = set()

    def first_time(self, src, mid):
        k = (src, mid)
        if k in self._s:
            return False
        self._s.add(k)
        self._q.append(k)
        if len(self._q) > self._cap:
            old = self._q.pop(0)
            self._s.discard(old)
        return True


def forward_copy(pkt):
    """Re-serialize a packet with ttl-1 for mesh relay, or None if ttl exhausted."""
    if pkt['ttl'] <= 1:
        return None
    return make_packet(pkt['src'], pkt['dst'], pkt['id'], pkt['payload'], pkt['ttl'] - 1)
