# novamesh: the LoRa packet layer (pure logic). Frame round-trip, CRC integrity,
# the dedup ring, and ttl forwarding — the foundation for multi-hop mesh relay.
import sys
import _shims
_shims.install()
from _shims import T
import novamesh as M

t = T('test_novamesh')

# --- make/parse round-trip ---
pkt = M.make_packet(0x0102, 0x0304, 0x0506, 'hi', ttl=3)
p = M.parse_packet(pkt)
t.ok(p is not None, 'valid packet parses')
t.eq(p['src'], 0x0102, 'src round-trips')
t.eq(p['dst'], 0x0304, 'dst round-trips')
t.eq(p['id'], 0x0506, 'id round-trips')
t.eq(p['ttl'], 3, 'ttl round-trips')
t.eq(p['payload'], b'hi', 'payload round-trips')

# str vs bytes payload are equivalent
t.eq(M.parse_packet(M.make_packet(1, 2, 3, b'\x00\xff'))['payload'], b'\x00\xff', 'raw bytes payload survives')

# broadcast dst
t.eq(M.parse_packet(M.make_packet(1, M.BROADCAST, 9, 'x'))['dst'], M.BROADCAST, 'broadcast dst preserved')

# payload is capped at 200 bytes
big = M.parse_packet(M.make_packet(1, 2, 3, 'A' * 500))
t.eq(len(big['payload']), 200, 'payload truncated to 200')

# --- CRC + framing rejection ---
bad = bytearray(pkt)
bad[-1] ^= 0xFF
t.eq(M.parse_packet(bytes(bad)), None, 'bad CRC rejected')
corrupt = bytearray(pkt)
corrupt[5] ^= 0x01                         # flip a header byte -> CRC mismatch
t.eq(M.parse_packet(bytes(corrupt)), None, 'corrupt header rejected')
t.eq(M.parse_packet(pkt[:5]), None, 'truncated packet rejected')
t.eq(M.parse_packet(b'\x00' * 12), None, 'wrong magic rejected')
t.eq(M.parse_packet(None), None, 'None rejected')

# --- dedup ring ---
s = M.Seen(cap=4)
t.ok(s.first_time(1, 100), 'first sighting is new')
t.ok(not s.first_time(1, 100), 'repeat sighting is a dup')
t.ok(s.first_time(1, 101), 'different id is new')
for i in range(200, 204):
    s.first_time(1, i)                     # overflow the ring past (1,100)
t.ok(s.first_time(1, 100), 'evicted key is seen as new again (bounded memory)')

# --- ttl forwarding (mesh relay) ---
fwd = M.forward_copy(p)                     # ttl 3 -> 2
t.eq(M.parse_packet(fwd)['ttl'], 2, 'forward decrements ttl')
t.eq(M.parse_packet(fwd)['payload'], b'hi', 'forward preserves payload')
t.eq(M.forward_copy({'src': 1, 'dst': 2, 'id': 3, 'ttl': 1, 'payload': b'x'}), None, 'ttl=1 is not forwarded')
t.eq(M.forward_copy({'src': 1, 'dst': 2, 'id': 3, 'ttl': 0, 'payload': b'x'}), None, 'ttl=0 is not forwarded')

# --- routing policy (multi-hop managed flood) ---
def _pk(src, dst, mid, ttl):
    return M.parse_packet(M.make_packet(src, dst, mid, 'x', ttl=ttl))

deliver, fwd = M.route(_pk(9, M.BROADCAST, 1, 3), me=5)
t.ok(deliver, 'broadcast is delivered')
t.ok(fwd is not None and M.parse_packet(fwd)['ttl'] == 2, 'broadcast is relayed (ttl-1)')

deliver, fwd = M.route(_pk(9, 5, 2, 3), me=5)
t.ok(deliver, 'unicast to me is delivered')
t.eq(fwd, None, 'unicast that reached me is NOT relayed')

deliver, fwd = M.route(_pk(9, 7, 3, 3), me=5)
t.ok(not deliver, "someone else's unicast is not delivered to me")
t.ok(fwd is not None, "but it IS relayed toward its destination")

deliver, fwd = M.route(_pk(9, 7, 4, 3), me=5, relay=False)
t.eq(fwd, None, 'relay=False never forwards')

deliver, fwd = M.route(_pk(9, M.BROADCAST, 5, 1), me=5)
t.ok(deliver and fwd is None, 'ttl-exhausted broadcast is delivered but not relayed')

# --- node_id from registry ---
_shims.set_reg({'Apps.NovaD1_NodeID': '4660'})   # 0x1234
t.eq(M.node_id(), 0x1234, 'node_id reads Apps.NovaD1_NodeID')

sys.exit(t.done())
