from . import tunnel
from . import constants
from . import util
import io
import time
import json
import re
import asyncio

class _BufferPipe(io.BufferedRandom):
    '''Class to approximate an os pipe in software. Feel like I'm an idiot and just can't find out how to do this with beffered readers, but here we are...'''

    def __init__(self, *args, **kwargs):
        _buffer = io.BytesIO()
        super().__init__(_buffer, *args, **kwargs)
        self._read_pointer = 0
        self._write_pointer = 0

    def peek(self, *args, **kwargs):
        self.seek(self._read_pointer)
        d = super().peek(*args, **kwargs)
        self._read_pointer = self.tell()
        return d

    def read(self, *args, **kwargs):
        self.seek(self._read_pointer)
        d = super().read(*args, **kwargs)
        self._read_pointer = self.tell()
        return d

    def read1(self, *args, **kwargs):
        self.seek(self._read_pointer)
        d = super().read1(*args, **kwargs)
        self._read_pointer = self.tell()
        return d

    def write(self, *args, **kwargs):
        self.seek(self._write_pointer)
        d = super().write(*args, **kwargs)
        self._write_pointer = self.tell()
        return d

class Shell(tunnel.Tunnel):
    def __init__(self, session, nodeid):
        super().__init__(session, nodeid, constants.Protocol.TERMINAL)
        self.recorded = None
        self._buffer = _BufferPipe()


    @util._check_socket
    async def write(self, command):
        """
        Write to the shell

        Args:
            command (str): Command to send

        Returns:
            None
        """
        return await self._message_queue.put(command.encode("utf-8"))

    @util._check_socket
    async def read(self, length=None, block=True, timeout=None):
        """
        Read data from the shell

        Args:
            length (int): Number of bytes to read. None == read until closed or timeout occurs.
            block (bool): block until n bytes are available or timeout occurs. If not, read at most until no data is returned. This may return an indeterminate amount of data.
            timeout (int): Milliseconds to wait for data. None == read until `length` bytes are read, or shell is closed.

        Returns:
            str: Data read. In the case of timeout, this will return all data read up to the timeout
        """
        start = time.time()
        ret = []
        read_bytes = 0
        while True:
            d = self._buffer.read1(length-read_bytes if length is not None else -1)
            # print(f"read: {d}")
            read_bytes += len(d)
            ret.append(d)
            if length is not None and read_bytes >= length:
                break
            if timeout is not None and time.time() - start >= timeout:
                break
            if not block and not len(d):
                break
            await asyncio.sleep(0)
        return b"".join(ret).decode("utf-8")

    @util._check_socket
    async def expect(self, regex, timeout=None):
        """
        Read data from the shell until `regex` is seen

        Args:
            regex (str|re.Pattern): Regex to check for match
            timeout (int): Milliseconds to wait for data. None == read until `length` bytes are read, or shell is closed.

        Returns:
            str: Data read.

        Raises:
            asyncio.TimeoutError: Regex not matched within timeout
        """
        start = time.time()
        read_bytes = 0
        if not isinstance(regex, re.Pattern):
            regex = re.compile(regex)
        while True:
            d = self._buffer.peek().decode("utf-8")
            match = regex.search(d)
            if match is not None:
                read_bytes = match.span()[1]
                break
            if timeout is not None and time.time() - start >= timeout:
                raise asyncio.TimeoutError
            await asyncio.sleep(0)
        return await self.read(read_bytes)

    async def _listen_data_task(self, websocket):
        async for message in websocket:
            if self.initialized.is_set():
                if message.startswith(b'{"ctrlChannel":"102938","type":"'):
                    try:
                        ctrl_cmd = json.loads(message)
                        # Skip control commands, like ping/pong
                        if ctrl_cmd.get("type", None) is not None:
                            return
                    except:
                        pass
                self._buffer.write(message)
            else:
                self.recorded = False
                if message == "cr":
                    self.recorded = True

                # Seems like we could use self.write here, but it won't have been initialized yet, so the socket check will fail.
                await self._message_queue.put(f"{self._protocol}".encode())
                self.alive = True
                self.initialized.set()



class SmartShell(object):
    def __init__(self, shell, regex):
        self._shell = shell
        self._regex = regex
        self._compiled_regex = re.compile(self._regex)
        self._init_task = asyncio.create_task(self._init())
        
    async def _init(self):
        # This comes twice. Test this for sanity. Seems meshcentral does some aliases when it logs in. Could be wrong on windows.
        await self._shell.expect(self._regex)
        await self._shell.expect(self._regex)


    @util._check_socket
    async def send_command(self, command, timeout=None):
        if not command.endswith("\n"):
            command += "\n"
        await self._shell.write(command)
        data = await self._shell.expect(self._regex, timeout=timeout)
        print(repr(data))
        return data[:self._compiled_regex.search(data).span()[0]]

    @property
    def alive(self):
        return self._shell.alive

    @property
    def closed(self):
        return self._shell.closed

    @property
    def initialized(self):
        return self._shell.initialized

    async def close(self):
        await self._init_task
        return await self._shell.close()

    async def __aenter__(self):
        await self._init_task
        await self._shell.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self._shell.__aexit__(*args)
