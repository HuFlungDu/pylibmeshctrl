import secrets
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import json
import base64
import asyncio
import collections
import re
import websockets
import ssl
import functools
from . import exceptions

def _encode_cookie(o, key):
    o["time"] = int(time.time()); # Add the cookie creation time
    iv = secrets.token_bytes(12)
    key = AESGCM(key)
    crypted = key.encrypt(iv, json.dumps(o), None)
    return base64.b64encode(crypted).replace(b"+", b'@').replace(b"/", b'$').decode("utf-8")

def _check_amt_password(p):
        return (len(p) > 7) and\
               (re.search(r"\d",p) is not None) and\
               (re.search(r"[a-z]",p) is not None) and\
               (re.search(r"[A-Z]",p) is not None) and\
               (re.search(r"\W",p) is not None)

def _get_random_amt_password():
    p = ""
    while not _check_amt_password(p):
        p = b"@".join(base64.b64encode(secrets.token_bytes(9)).split(b'/')).decode("utf-8")
    return p

def _get_random_hex(count):
    return secrets.token_bytes(count).hex();

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

    async def emit(self, event, data):
        """
        Emit `event` with `data`. All subscribed functions will be called (order is nonsensical).

        Args:
            event (str): Event name emit
            data (object): Data to pass to all the bound functions
        """
        for f in self._onces.get(event, []):
            await f(data)
        try:
            del self._onces[event]
        except KeyError:
            pass
        for f in self._ons.get(event, []):
            await f(data)
        
def compare_dict(dict1, dict2):
    try:
        if dict1 == dict2:
            return True
        for key, val in dict1.items():
            if key not in dict2:
                return False

            if type(val) is dict:
                if not compare_dict(val, dict2[key]):
                    return False
            elif type(val) is set:
                for v in val:
                    for v2 in dict2[key]:
                        try:
                            if compare_dict(v, v2):
                                break
                        except:
                            pass
                    else:
                        return False
            elif isinstance(val, collections.abc.Iterable):
                # We don't want strings to match other iterables, so check that
                if isinstance(val, str) or isinstance(dict2[key], str):
                    if not isinstance(val, type(dict2[key])):
                        return False
                try:
                    if (len(val) != len(dict2[key])):
                        return False
                    for i, v in enumerate(val):
                        if not compare_dict(v, dict2[key][i]):
                            return False
                except Exception as e:
                    return False
            elif (dict2[key] != val):
                return False
        return True
    except Exception:
        return False

def _check_socket(f):
    @functools.wraps(f)
    async def wrapper(self, *args, **kwargs):
        await self.initialized.wait()
        if not self.alive and self._main_loop_error is not None:
            raise self._main_loop_error
        elif not self.alive:
            raise exceptions.SocketError("Socket Closed")
        return await f(self, *args, **kwargs)
    return wrapper

def _process_websocket_exception(exc):
    tmp = websockets.asyncio.client.process_exception(exc)
    # SSLVerification error is a subclass of OSError, but doesn't make sense no retry, so we need to handle it separately.
    if isinstance(exc, (ssl.SSLCertVerificationError, TimeoutError)):
        return exc
    return tmp
