from . import tunnel
from . import constants
from . import exceptions
from . import util
import asyncio
import json
import importlib
import importlib.util
import shutil

# import urllib
# import urllib.request
import urllib.parse
old_parse = urllib.parse
# Default proxy handler uses OS defined no_proxy in order to be helpful. This is unhelpful for our usecase. Monkey patch out proxy getting functions, but don't effect the user's urllib instance.
spec = importlib.util.find_spec('urllib')
urllib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(urllib)
spec = importlib.util.find_spec('urllib.request')
urllib.request = importlib.util.module_from_spec(spec)
spec.loader.exec_module(urllib.request)
urllib.parse = old_parse
urllib.request.getproxies_environment = lambda: {}
urllib.request.getproxies_registry = lambda: {}
urllib.request.getproxies_macosx_sysconf = lambda: {}
urllib.request.getproxies = lambda: {}

class Files(tunnel.Tunnel):
    def __init__(self, session, node):
        super().__init__(session, node.nodeid, constants.Protocol.FILES)
        self.recorded = None
        self._node = node
        self._request_id = 0
        self._request_queue = asyncio.Queue()
        self._download_finished = asyncio.Event()
        self._download_finished.set()
        self._current_request = None
        self._handle_requests_task = asyncio.create_task(self._handle_requests())
        self._chunk_size = 65564
        proxies = {}
        if self._session._proxy is not None:
            # We don't know which protocol the user is going to use, but we only need support one at a time, so just assume both
            proxies = {
                "http": self._session._proxy,
                "https": self._session._proxy,
                "no": ""
            }
        self._proxy_handler = urllib.request.ProxyHandler(proxies=proxies)
        self._http_opener = urllib.request.build_opener(self._proxy_handler, urllib.request.HTTPSHandler(context=self._session._ssl_context))


    def _get_request_id(self):
        self._request_id = (self._request_id+1)%(2**32-1)
        return self._request_id

    async def close(self):
        self._handle_requests_task.cancel()
        try:
            await self._handle_requests_task
        except asyncio.CancelledError:
            pass
        await super().close()

    async def _handle_requests(self):
        try:
            while True:
                request = await self._request_queue.get()
                self._current_request = request
                self._download_finished = request["finished"]
                await self._message_queue.put(json.dumps(request["data"]))
                await request["finished"].wait()
                self._current_request = None

        except asyncio.CancelledError:
            while True:
                try:
                    request = self._request_queue.get_nowait()
                    request["error"] = exceptions.SocketError("Socket Closed")
                    request["errored"].set()
                    request["finished"].set()
                except asyncio.QueueEmpty:
                    break
            raise
            

    @util._check_socket
    async def _send_command(self, data, name, timeout=None):
        request_id = f"meshctrl_{name}_{self._get_request_id()}"
        request = {"id": request_id, "data": data, "return": None, "type": name, "finished": asyncio.Event(), "errored":asyncio.Event(), "error": None}
        await self._request_queue.put(request)

        await asyncio.wait_for(request["finished"].wait(), timeout=timeout)
        if request["error"] is not None:
            raise request["error"]
        return request["return"]

    async def ls(self, directory, timeout=None):
        """
        Return a directory listing from the device

        Args:
            directory (str): Path to the directory you wish to list
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[~meshctrl.types.FilesLSItem]: The directory listing

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error from server
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        """
        data = await self._send_command({"action": "ls", "path": directory}, "ls", timeout=timeout)
        return data["dir"]

    async def _listen_for_pass(self, tasks):
        async for event in self._session.events({"event": {"etype": "node", "action": "agentlog"}}):
            if not event["event"]["msg"].startswith("Started"):
                self._current_request["return"] = event["event"]["msg"]
                self._current_request["finished"].set()
                tasks[1].cancel()
                break

    async def _listen_for_error(self, tasks):
        async for event in self._session.events({"action":"msg", "type":"console"}):
            self._current_request["error"] = exceptions.ServerError(event["value"])
            self._current_request["errored"].set()
            self._current_request["finished"].set()
            tasks[0].cancel()
            break

    async def mkdir(self, directory, timeout=None):
        """
        Create a directory on the device

        Args:
            directory (str): Path of directory to create
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error from server
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out

        Returns:
            bool: True if directory was created
        """
        tasks = []
        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(asyncio.wait_for(self._listen_for_pass(tasks), timeout)))
            tasks.append(tg.create_task(asyncio.wait_for(self._listen_for_error(tasks), timeout)))
            tasks.append(tg.create_task(self._send_command({"action": "mkdir", "path": directory}, "mkdir", timeout=timeout)))



        return tasks[2].result().startswith("Create folder")

    async def rm(self, path, files, recursive=False, timeout=None):
        """
        Remove a set of files or directories from the device. This API doesn't error if the file doesn't exist.

        Args:
            path (str): Directory from which to delete files
            files (str|list[str]): File or files to remove from the directory
            recursive (bool): Whether to delete the files recursively
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error from server
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out

        Returns:
            str: Info about the files removed. Something along the lines of Delete: "/path/to/file", or 'Delete recursive: "/path/to/dir", n element(s) removed'.
        """
        if isinstance(files, str):
            files = [files]
        tasks = []

        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(asyncio.wait_for(self._listen_for_pass(tasks), timeout)))
            tasks.append(tg.create_task(asyncio.wait_for(self._listen_for_error(tasks), timeout)))
            tasks.append(tg.create_task(self._send_command({"action": "rm", "delfiles": files, "rec": recursive, "path": path}, "rm", timeout=timeout)))


        return tasks[2].result()

    async def rename(self, path, name, new_name, timeout=None):
        """
        Rename a file or folder on the device. This API doesn't error if the file doesn't exist.

        Args:
            path (str): Directory from which to rename the file
            name (str): File to rename
            new_name (str): New name to give the file
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error from server
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out

        Returns:
            str: Info about file renamed. Something along the lines of 'Rename: "/path/to/file" to "newfile"'.
        """
        tasks = []

        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(asyncio.wait_for(self._listen_for_pass(tasks), timeout)))
            tasks.append(tg.create_task(asyncio.wait_for(self._listen_for_error(tasks), timeout)))
            tasks.append(tg.create_task(self._send_command({"action": "rename", "path": path, "oldname": name, "newname": new_name}, "rename", timeout=timeout)))


        return tasks[2].result()

    @util._check_socket
    async def upload(self, source, target, name=None, timeout=None):
        '''
        Upload a stream to a device.

        Args:
            source (io.IOBase): An IO instance from which to read the data. Must be open for reading.
            target (str): Path which to upload stream to on remote device
            name (str): Pass if target points at a directory instead of the file path. In that case, this will be the name of the file.
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.FileTransferError`: File transfer failed. Info available on the `stats` property
            :py:class:`~meshctrl.exceptions.FileTransferCancelled`: File transfer cancelled. Info available on the `stats` property
            asyncio.TimeoutError: Command timed out

        Returns:
            dict: {result: bool whether upload succeeded, size: number of bytes uploaded}
        '''
        request_id = f"upload_{self._get_request_id()}"
        data = { "action": 'upload', "reqid": request_id, "path": target, "name": name}
        request = {"id": request_id, "data": data, "type": "upload", "source": source, "target": target, "name": name, "size": 0, "complete": False, "inflight": 0, "finished": asyncio.Event(), "errored":asyncio.Event(), "error": None}
        await self._request_queue.put(request)
        await asyncio.wait_for(request["finished"].wait(), timeout)
        if request["error"] is not None:
            raise request["error"]
        return request["return"]

    def _http_download(self, url, target, timeout):
        response = self._http_opener.open(url, timeout=timeout)
        shutil.copyfileobj(response, target)

    @util._check_socket
    async def download(self, source, target, skip_http_attempt=False, skip_ws_attempt=False, timeout=None):
        '''
        Download a file from a device into a writable stream.

        Args:
            source (str): Path from which to download from device
            target (io.IOBase): Stream to which to write data. If None, create new BytesIO which is both readable and writable.
            skip_http_attempt (bool): Meshcentral has a way to download files through http(s) instead of through the websocket. This method tends to be much faster than using the websocket, so we try it first. Setting this to True will skip that attempt and just use the established websocket connection.
            skip_ws_attempt (bool): Like skip_http_attempt, except just throw an error if the http attempt fails instead of trying with the websocket
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.FileTransferError`: File transfer failed. Info available on the `stats` property
            :py:class:`~meshctrl.exceptions.FileTransferCancelled`: File transfer cancelled. Info available on the `stats` property
            asyncio.TimeoutError: Command timed out

        Returns:
            dict: {result: bool whether download succeeded, size: number of bytes downloaded}
        '''
        request_id = f"download_{self._get_request_id()}"
        data = { "action": 'download', "sub": 'start', "id": request_id, "path": source }
        request = {"id": request_id, "data": data, "type": "download", "source": source, "target": target, "size": 0, "finished": asyncio.Event(), "errored": asyncio.Event(), "error": None}
        if not skip_http_attempt:
            start_pos = target.tell()
            try:
                params = urllib.parse.urlencode({
                    "c": self._authcookie["cookie"],
                    "m": self._node.mesh.meshid.split("/")[-1],
                    "n": self._node.nodeid.split("/")[-1],
                    "f": source
                })
                url = self._session.url.replace('/control.ashx', f"/devicefile.ashx?{params}")
                url = url.replace("wss://", "https://").replace("ws://", "http://")

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._http_download, url, target, timeout)
                size = target.tell() - start_pos
                return {"result": True, "size": size}
            except* Exception as eg:
                if skip_ws_attempt:
                    size = target.tell() - start_pos
                    excs = eg.exceptions + (exceptions.FileTransferError("Errored", {"result": False, "size": size}),)
                    raise ExceptionGroup("File download failed", excs)
                target.seek(start_pos)

        await self._request_queue.put(request)
        await asyncio.wait_for(request["finished"].wait(), timeout)
        if request["error"] is not None:
            raise request["error"]
        return request["return"]

    async def _handle_upload(self, data):
        cmd = None
        try:
            cmd = json.loads(data)
        except:
            return
        if cmd["reqid"] == self._current_request["id"]:
            if cmd["action"] == "uploaddone":
                self._current_request["return"] = {"result": True, "size": self._current_request["size"]}
                self._current_request["finished"].set()
            elif cmd["action"] == "uploadstart":
                while True:
                    data = self._current_request["source"].read(self._chunk_size)
                    if len(data) == 0:
                        self._current_request["complete"] = True
                        if self._current_request["inflight"] == 0:
                            await self._message_queue.put(json.dumps({ "action": 'uploaddone', "reqid": self._current_request["id"]}))
                        break
                    else:
                        self._current_request["size"] += len(data)
                        if data[0] == 0 or data[0] == 123:
                            data = b'\0' + data
                        await self._message_queue.put(data)
                        self._current_request["inflight"] += 1
                    await asyncio.sleep(0)
            elif cmd["action"] == "uploadack":
                self._current_request["inflight"] -= 1
                if self._current_request["inflight"] == 0 and self._current_request["complete"]:
                    await self._message_queue.put(json.dumps({ "action": 'uploaddone', "reqid": self._current_request["id"]}))
            elif cmd["action"] == "uploaderror":
                self._current_request["return"] = {"result": False, "size": self._current_request["size"]}
                self._current_request["error"] = exceptions.FileTransferError("Errored", self._current_request["return"])
                self._current_request["errored"].set()
                self._current_request["finished"].set()

    async def _handle_download(self, data):
        cmd = None
        try:
            cmd = json.loads(data)
        except:
            pass
        if cmd is None:
            if len(data) > 4:
                self._current_request["target"].write(data[4:])
                self._current_request["size"] += len(data)-4
            if (data[3] & 1) != 0:
                self._current_request["return"] = {"result": True, "size": self._current_request["size"]}
                self._current_request["finished"].set()
            else:
                await self._message_queue.put(json.dumps({ "action": 'download', "sub": 'ack', "id": self._current_request["id"] }))
        else:
            if cmd["action"] == "download":
                if cmd["id"] != self._current_request["id"]:
                    return
                if cmd["sub"] == "start":
                    await self._message_queue.put(json.dumps({ "action": 'download', "sub": 'startack', "id": self._current_request["id"] }))
                elif cmd["sub"] == "cancel":
                    self._current_request["return"] = {"result": False, "size": self._current_request["size"]}
                    self._current_request["error"] = exceptions.FileTransferCancelled("Cancelled", self._current_request["return"])
                    self._current_request["errored"].set()
                    self._current_request["finished"].set()

    async def _handle_action(self, data):
        self._current_request["return"] = json.loads(data)
        self._download_finished.set()


    async def _listen_data_task(self, websocket):
        async for message in websocket:
            if self.initialized.is_set():
                if message[0] == 123 and self._current_request is not None and self._current_request["type"] not in ("upload", "download"):
                    await self._handle_action(message)
                elif self._current_request is not None and self._current_request["type"] == "upload":
                    await self._handle_upload(message)
                elif self._current_request is not None and self._current_request["type"] == "download":
                    await self._handle_download(message)
            else:
                self.recorded = False
                if message == "cr":
                    self.recorded = True

                await self._message_queue.put(f"{self._protocol}".encode())
                self.alive = True
                self.initialized.set()