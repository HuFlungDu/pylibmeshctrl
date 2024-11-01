import secrets
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import json
import base64

def encode_cookie(o, key):
    o["time"] = int(time.time()); # Add the cookie creation time
    iv = secrets.token_bytes(12)
    key = AESGCM(key)
    crypted = key.encrypt(iv, json.dumps(o), None)
    return base64.b64encode(crypted).replace("+", '@').replace("/", '$');

class Eventer(object):
    def __init__(self):
        self._ons = {}
        self._onces = {}

    def on(self, event, func):
        self._ons.setdefault(event, set()).add(func)

    def once(self, event, func):
        self._onces.setdefault(event, set()).add(func)

    def off(self, event, func):
        try:
            self._onces.setdefault(event, set()).remove(func)
        except KeyError:
            pass
        try:
            self._ons.setdefault(event, set()).remove(func)
        except KeyError:
            pass

    def emit(self, event, data):
        for f in self._onces.get(event, []):
            f(data)
        try:
            del self._onces[event]
        except KeyError:
            pass
        for f in self._ons.get(event, []):
            f(data)
        