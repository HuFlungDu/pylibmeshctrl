import websockets
import websockets.datastructures
import websockets.asyncio
import websockets.asyncio.client
import asyncio
import ssl
from . import exceptions
from . import util
from . import constants

class Tunnel(object):
    def __init__(self, session, node_id, protocol):
        self._session = session
        self.node_id = node_id
        self._protocol = protocol
        self._tunnel_id = None
        self.url = None
        self._socket_open = asyncio.Event()
        self._main_loop_error = None
        self.initialized = asyncio.Event()
        self.alive = False
        self.closed = asyncio.Event()
        self._main_loop_task = asyncio.create_task(self._main_loop())

        self._message_queue = asyncio.Queue()
        self._send_task = None
        self._listen_task = None

    async def close(self):
        self._main_loop_task.cancel()
        try:
            await self._main_loop_task
        except asyncio.CancelledError:
            pass

    async def __aenter__(self):
        # If we take more than 10 seconds to establish a tunnel, something is up.
        await asyncio.wait_for(self.initialized.wait(), 10)
        return self

    async def __aexit__(self, exc_t, exc_v, exc_tb):
        await self.close()

    async def _main_loop(self):
        try:
            authcookie = await self._session._send_command_no_response_id({ "action":"authcookie" })

            options = {}
            if self._session._ignore_ssl:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                options = { "ssl": ssl_context }

            # Setup the HTTP proxy if needed
            # if (self._session._proxy != None):
            #     options.agent = new https_proxy_agent(urllib.parse(this._proxy))

            if (self.node_id.split('/') != 3) and (self._session._currentDomain is not None):
                self.node_id = f"node/{self._session._currentDomain}/{self.node_id}"

            self._tunnel_id = util._get_random_hex(6)

            initialize_tunnel_response = await self._session._send_command({ "action": 'msg', "nodeid": self.node_id, "type": 'tunnel', "usage": 1, "value": '*/meshrelay.ashx?p=' + str(self._protocol) + '&nodeid=' + self.node_id + '&id=' + self._tunnel_id + '&rauth=' + authcookie["rcookie"] }, "initialize_tunnel")

            if initialize_tunnel_response.get("result", None) != "OK":
                self._main_loop_error = exceptions.ServerError(initialize_tunnel_response.get("result", "Failed to initialize remote tunnel"))
                self._socket_open.clear()
                self.closed.set()
                self.initialized.set()
                return

            self.url = self._session.url.replace('/control.ashx', '/meshrelay.ashx?browser=1&p=' + str(self._protocol) + '&nodeid=' + self.node_id + '&id=' + self._tunnel_id + '&auth=' + authcookie["cookie"])

            # headers = websockets.datastructures.Headers()

            # if (self._password):
            #     token = self._token if self._token else b""
            #     headers['x-meshauth'] = (base64.b64encode(self._user.encode()) + b',' + base64.b64encode(self._password.encode()) + token).decode()

            # options["additional_headers"] = headers
            async for websocket in websockets.asyncio.client.connect(self.url, process_exception=util._process_websocket_exception, **options):
                self.alive = True
                self._socket_open.set()
                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._listen_data_task(websocket))
                        tg.create_task(self._send_data_task(websocket))
                except* websockets.ConnectionClosed as e:
                    self._socket_open.clear()
                    if not self.auto_reconnect:
                        self.alive = False
                        raise
        except* Exception as eg:
            self.alive = False
            self._socket_open.clear()
            self._main_loop_error = eg
            self.closed.set()
            self.initialized.set()

    async def _send_data_task(self, websocket):
        while True:
            message = await self._message_queue.get()
            await websocket.send(message)

    async def _listen_data_task(self, websocket):
        raise NotImplementedError("Listen data not implemented")