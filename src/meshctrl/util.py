import secrets
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import json
import base64

def _encode_cookie(o, key):
    o["time"] = int(time.time()); # Add the cookie creation time
    iv = secrets.token_bytes(12)
    key = AESGCM(key)
    crypted = key.encrypt(iv, json.dumps(o), None)
    return base64.b64encode(crypted).replace("+", '@').replace("/", '$');

class Eventer(object):
    """
    Eventer object to allow pub/sub interactions with a Session object
    """
    def __init__(self):
        self._ons = {}
        self._onces = {}

    def on(self, event, func):
        """
        Subscribe to `event`. `func` will be called when that event is emitted.

        Args:
            event (str): Event name to subscribe to
            func (function(data: object)): Function to call when event is emitted. `data` could be of any type. Also used as a key to remove this subscription.
        """
        self._ons.setdefault(event, set()).add(func)

    def once(self, event, func):
        """
        Subscribe to `event` once. `func` will be called when that event is emitted. The binding will then be removed.

        Args:
            event (str): Event name to subscribe to
            func (function(data: object)): Function to call when event is emitted. `data` could be of any type. Also used as a key to remove this subscription.
        """
        self._onces.setdefault(event, set()).add(func)

    def off(self, event, func):
        """
        Unsubscribe from `event`. `func` is the object originally passed during the bind.

        Args:
            event (str): Event name to unsubscribe from
            func (object): Function which was originally passed when subscribing.
        """
        try:
            self._onces.setdefault(event, set()).remove(func)
        except KeyError:
            pass
        try:
            self._ons.setdefault(event, set()).remove(func)
        except KeyError:
            pass

    def emit(self, event, data):
        """
        Emit `event` with `data`. All subscribed functions will be called (order is nonsensical).

        Args:
            event (str): Event name emit
            data (object): Data to pass to all the bound functions
        """
        for f in self._onces.get(event, []):
            f(data)
        try:
            del self._onces[event]
        except KeyError:
            pass
        for f in self._ons.get(event, []):
            f(data)
        