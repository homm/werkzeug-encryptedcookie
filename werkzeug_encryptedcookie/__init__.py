import base64
import json
import struct
import zlib
from time import time

import brotli
from Crypto import Random
from Crypto.Cipher import ARC4
from Crypto.Hash import SHA
from secure_cookie.cookie import _date_to_unix, SecureCookie


class EncryptedCookie(SecureCookie):
    compress_cookie = True
    compress_cookie_header = b'~!~brtl~!~'
    # to avoid deprecation warnings
    serialization_method = json

    @classmethod
    def _get_cipher(cls, key):
        return ARC4.new(SHA.new(key).digest())

    @classmethod
    def dumps(cls, data):
        # dict -> bytes
        return json.dumps(data, ensure_ascii=False).encode('utf-8')

    @classmethod
    def encrypt(cls, data, secret_key):
        # bytes + key -> bytes
        nonce = Random.new().read(16)
        cipher = cls._get_cipher(secret_key + nonce)
        return nonce + cipher.encrypt(data)

    @classmethod
    def compress(cls, data):
        return cls.compress_cookie_header + brotli.compress(data, quality=8)

    def serialize(self, expires=None):
        if self.secret_key is None:
            raise RuntimeError('no secret key defined')

        data = dict(self)
        if expires:
            data['_expires'] = _date_to_unix(expires)

        payload = self.dumps(data)

        if self.compress_cookie:
            payload = self.compress(payload)

        string = self.encrypt(payload, self.secret_key)

        if self.quote_base64:
            # bytes -> ascii bytes
            string = base64.b64encode(string)

        return string

    @classmethod
    def loads(cls, data):
        # bytes -> dict
        return json.loads(data.decode('utf-8'))

    @classmethod
    def decrypt(cls, string, secret_key):
        # bytes + key -> bytes
        nonce, payload = string[:16], string[16:]

        cipher = cls._get_cipher(secret_key + nonce)
        return cipher.decrypt(payload)

    @classmethod
    def decompress(cls, data):
        if data.startswith(cls.compress_cookie_header):
            body = data[len(cls.compress_cookie_header):]
            try:
                return brotli.decompress(body)
            except brotli.error:
                pass

        return data

    @classmethod
    def unserialize(cls, string, secret_key):
        if cls.quote_base64:
            try:
                # ascii bytes -> bytes
                string = base64.b64decode(string)
            except Exception:
                pass

        payload = cls.decrypt(string, secret_key)
        payload = cls.decompress(payload)

        try:
            data = cls.loads(payload)
        except ValueError:
            data = None

        if data and '_expires' in data:
            if time() > data['_expires']:
                data = None
            else:
                del data['_expires']

        return cls(data, secret_key, False)


class SecureEncryptedCookie(EncryptedCookie):
    @classmethod
    def encrypt(cls, data, secret_key):
        crc = zlib.crc32(data, zlib.crc32(secret_key))
        data += struct.pack('>I', crc & 0xffffffff)
        return super(SecureEncryptedCookie, cls).encrypt(data, secret_key)

    @classmethod
    def decrypt(cls, string, secret_key):
        data = super(SecureEncryptedCookie, cls).decrypt(string, secret_key)
        data, crc1 = data[:-4], data[-4:]
        crc2 = zlib.crc32(data, zlib.crc32(secret_key))
        if crc1 != struct.pack('>I', crc2 & 0xffffffff):
            return b''
        return data
