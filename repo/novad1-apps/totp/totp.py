# TOTP — a kind:py Nova D1 app. A 2FA authenticator (RFC 6238, SHA1).
#
# Each account is a .txt in the Nova 'totp' store whose content is a base32 secret
# (optionally 'Label: SECRET'). Turn switches account; the current 6-digit code +
# seconds-remaining show live. The whole crypto chain is pure Python — a self-
# contained SHA1 + HMAC so it works on any MicroPython build (no hashlib needed),
# and it's verified against the RFC 6238 test vectors + CPython hashlib in the suite.
#
# Needs the clock set (NTP on first WiFi connect does this). Binds only to the
# injected `ui` / `ev` / `nova` (nova.list_codes / nova.read_code). No f-strings.

TITLE = 'TOTP'
CATEGORY = 'System'

_B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'


def _rol(v, n):
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF


def _sha1(msg):
    """Pure-Python SHA-1 -> 20-byte digest. Verified against hashlib in the suite."""
    h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0
    ml = len(msg) * 8
    msg = msg + b'\x80'
    while len(msg) % 64 != 56:
        msg = msg + b'\x00'
    msg = msg + ml.to_bytes(8, 'big')
    for i in range(0, len(msg), 64):
        chunk = msg[i:i + 64]
        w = [0] * 80
        for j in range(16):
            w[j] = int.from_bytes(chunk[j * 4:j * 4 + 4], 'big')
        for j in range(16, 80):
            w[j] = _rol(w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16], 1)
        a, b, c, d, e = h0, h1, h2, h3, h4
        for j in range(80):
            if j < 20:
                f = (b & c) | ((b ^ 0xFFFFFFFF) & d)
                k = 0x5A827999
            elif j < 40:
                f = b ^ c ^ d
                k = 0x6ED9EBA1
            elif j < 60:
                f = (b & c) | (b & d) | (c & d)
                k = 0x8F1BBCDC
            else:
                f = b ^ c ^ d
                k = 0xCA62C1D6
            t = (_rol(a, 5) + f + e + k + w[j]) & 0xFFFFFFFF
            e = d
            d = c
            c = _rol(b, 30)
            b = a
            a = t
        h0 = (h0 + a) & 0xFFFFFFFF
        h1 = (h1 + b) & 0xFFFFFFFF
        h2 = (h2 + c) & 0xFFFFFFFF
        h3 = (h3 + d) & 0xFFFFFFFF
        h4 = (h4 + e) & 0xFFFFFFFF
    return (h0.to_bytes(4, 'big') + h1.to_bytes(4, 'big') + h2.to_bytes(4, 'big') +
            h3.to_bytes(4, 'big') + h4.to_bytes(4, 'big'))


def _hmac_sha1(key, msg):
    if len(key) > 64:
        key = _sha1(key)
    key = key + b'\x00' * (64 - len(key))
    o = bytes(kb ^ 0x5C for kb in key)
    i = bytes(kb ^ 0x36 for kb in key)
    return _sha1(o + _sha1(i + msg))


def _b32decode(s):
    s = s.strip().replace(' ', '').replace('-', '').upper()
    while s and s[-1] == '=':
        s = s[:-1]
    bits = 0
    val = 0
    out = bytearray()
    for ch in s:
        idx = _B32.find(ch)
        if idx < 0:
            continue
        val = (val << 5) | idx
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((val >> bits) & 0xFF)
    return bytes(out)


def totp(secret_b32, unix_t, step=30, digits=6):
    """The current TOTP code for a base32 secret at a Unix time. Pure; the tested core."""
    key = _b32decode(secret_b32)
    ctr = int(unix_t) // step
    h = _hmac_sha1(key, ctr.to_bytes(8, 'big'))
    off = h[-1] & 0x0F
    code = (((h[off] & 0x7F) << 24) | (h[off + 1] << 16) |
            (h[off + 2] << 8) | h[off + 3]) % (10 ** digits)
    return ('{:0' + str(digits) + 'd}').format(code)


def _now():
    try:
        import utime
        t = int(utime.time())
    except Exception:
        return 0
    if t < 1000000000:                 # MicroPython 2000-epoch value -> shift to Unix
        t += 946684800
    return t


class Totp(ui.Screen):
    title = 'TOTP'

    def __init__(self):
        try:
            self.accts = list(nova.list_codes('totp') or [])
        except Exception:
            self.accts = []
        self.idx = 0
        self.code = '------'
        self.left = 0
        self._last = -1
        self._refresh()

    def _secret(self):
        if not self.accts:
            return None
        try:
            txt = nova.read_code('totp', self.accts[self.idx]) or ''
        except Exception:
            return None
        for line in txt.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' in line:
                line = line.rsplit(':', 1)[1]      # 'GitHub: ABC...' -> 'ABC...'
            return line.strip()
        return None

    def _refresh(self):
        s = self._secret()
        if not s:
            self.code = '------'
            self.left = 0
            return
        t = _now()
        try:
            self.code = totp(s, t)
        except Exception:
            self.code = 'ERR'
        self.left = 30 - (t % 30)

    def draw(self, c):
        if not self.accts:
            c.text(2, ui._TOP, 'No TOTP accounts', 1)
            c.text(2, ui._TOP + ui._ROWH, "add a .txt to the", 1)
            c.text(2, ui._TOP + 2 * ui._ROWH, "'totp' folder: your", 1)
            c.text(2, ui._TOP + 3 * ui._ROWH, 'base32 secret', 1)
            c.text(2, c.h - ui._FH, 'BACK = exit', 1)
            return
        name = self.accts[self.idx].rsplit('.', 1)[0]
        c.text(2, ui._TOP, name[:21], 1)
        disp = self.code
        if len(disp) == 6:
            disp = disp[:3] + ' ' + disp[3:]
        x = max(0, (c.w - len(disp) * ui._ADV * 2) // 2)
        c.text(x, ui._TOP + ui._ROWH, disp, 1, 2)
        bw = c.w - 8
        c.rect(2, ui._TOP + 3 * ui._ROWH, bw, 5, 1)
        c.fill_rect(3, ui._TOP + 3 * ui._ROWH + 1, int((bw - 2) * self.left / 30), 3, 1)
        c.text(2, c.h - ui._FH, '{}/{}  {}s'.format(self.idx + 1, len(self.accts), self.left), 1)

    def tick(self, dt_ms=0):
        t = _now()
        if t != self._last:                        # once per second
            self._last = t
            self._refresh()
            return True
        return False

    def on_event(self, e):
        if e == ev.ROT_CW and self.accts:
            self.idx = (self.idx + 1) % len(self.accts)
            self._refresh()
            return None
        if e == ev.ROT_CCW and self.accts:
            self.idx = (self.idx - 1) % len(self.accts)
            self._refresh()
            return None
        if e in (ev.BACK, ev.HOME):
            return e
        return None


def app():
    return Totp()
