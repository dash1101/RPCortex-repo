# Desc: Nova D1 LoRa payload encryption — AES-128-CBC with a shared passphrase.
# File: /Packages/NovaD1/novacrypt.py
#
# Optional end-to-end encryption for LoRa P2P: set the same passphrase on two D1s
# (Apps.NovaD1_LoRa_Key) and their messages are AES-encrypted over the air — a node
# without the key just sees '[encrypted]'. Key = SHA-256(passphrase)[:16]; a random
# 16-byte IV is prepended per message; PKCS7 padding. Uses the ESP32 hardware AES
# via cryptolib/ucryptolib (device-only). MicroPython-safe.

_MARK = 0xE5            # payload[0] flag: this message is encrypted


from novacore import reg as _reg


def have_key():
    return bool(_reg('Apps.NovaD1_LoRa_Key', ''))


def _key():
    import hashlib
    return hashlib.sha256(_reg('Apps.NovaD1_LoRa_Key', '').encode()).digest()[:16]


def _aes(key, iv):
    try:
        import cryptolib as cl
    except ImportError:
        import ucryptolib as cl
    return cl.aes(key, 2, iv)              # mode 2 = CBC


def _rand(n):
    try:
        import os
        return os.urandom(n)
    except Exception:
        import urandom
        return bytes(urandom.getrandbits(8) for _ in range(n))


def encrypt(data):
    """plaintext bytes -> MARK + IV(16) + ciphertext. None on failure."""
    try:
        if isinstance(data, str):
            data = data.encode('utf-8')
        pad = 16 - (len(data) % 16)
        data = data + bytes([pad]) * pad   # PKCS7
        iv = _rand(16)
        return bytes([_MARK]) + iv + _aes(_key(), iv).encrypt(data)
    except Exception:
        return None


def is_encrypted(payload):
    return bool(payload) and payload[0] == _MARK


def decrypt(payload):
    """MARK+IV+ct -> plaintext bytes, or None (no key / wrong key / not encrypted)."""
    try:
        if not is_encrypted(payload) or len(payload) < 33:
            return None
        iv = payload[1:17]
        ct = payload[17:]
        pt = _aes(_key(), iv).decrypt(ct)
        pad = pt[-1]
        if pad < 1 or pad > 16:
            return None
        return pt[:-pad]
    except Exception:
        return None
