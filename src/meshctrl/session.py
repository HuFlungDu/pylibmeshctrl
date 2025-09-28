import websockets
import websockets.datastructures
import websockets.asyncio
import websockets.asyncio.client
import asyncio
import base64
import json
import datetime
import io
import ssl
import urllib
from python_socks.async_.asyncio import Proxy
from platform import python_version
from . import __version__
from . import constants
from . import exceptions
from . import util
from . import shell
from . import files
from . import mesh
from . import device
from . import user_group

class Session(object):

    '''
    Class for MeshCentral control session

    Args:
        url (str): URL of meshcentral server to connect to. Should start with either "ws://" or "wss://".
        user (str): Username of to use for connecting. Can also be username generated from token.
        domain (str): Domain to connect to
        password (str): Password with which to connect. Can also be password generated from token.
        loginkey (str|bytes): Key from already handled login. Overrides username/password.
        proxy (str): "url:port" to use for proxy server
        token (str): Login token. This appears to be superfluous
        ignore_ssl (bool): Ignore SSL errors
        auto_reconnect (bool): In case of server failure, attempt to auto reconnect. All outstanding requests will be killed.

    Returns:
        :py:class:`Session`: Session connected to url

    Attributes:
        url (str): url to which the session is connected
        initialized (asyncio.Event): Event marking if the Session initialization has finished. Wait on this to wait for a connection.
        alive (bool): Whether the session connection is currently alive
        closed (asyncio.Event): Event that occurs when the session closes permanently
    '''

    def __init__(self, url, user=None, domain=None, password=None, loginkey=None, proxy=None, token=None, ignore_ssl=False, auto_reconnect=False, user_agent_header=None):
        default_user_agent_header = f"Python/{python_version()} websockets/{websockets.__version__} pylibmeshctrl/{__version__}" 
        parsed = urllib.parse.urlparse(url)

        if parsed.scheme not in ("wss", "ws"):
            raise ValueError("Invalid URL")

        port = 80
        if parsed.port is None:
            if parsed.scheme == "wss":
                port = 443
            p = list(parsed)
            p[1] = f"{parsed.hostname}:{port}"
            url = urllib.parse.urlunparse(p)

        if (not url.endswith('/')):
            url += '/'

        url += 'control.ashx'

        if (not user or (not password and not loginkey)):
            raise exceptions.MeshCtrlError("No login credentials given")

        if loginkey:
            try:
                with open(loginkey, "r") as infile:
                    loginkey = infile.read()
            except FileNotFoundError:
                pass

            ckey = loginkey
            try:
                ckey = bytes.fromhex(loginkey)
            except:
                pass
                
            if len(ckey) != 80: 
                raise ValueError("Invalid login key")
            domainid = '',
            username = 'admin'
            if (domain != None):
                domainid = domain
            if (user != None):
                username = user
            url += '?auth=' + util._encode_cookie({ userid: 'user/' + domainid + '/' + username, domainid: domainid }, ckey)

        if token:
            token = b',' + base64.b64encode(token.encode())
        
        self.url = url
        self._proxy = proxy
        self._user = user
        self._domain = domain
        self._currentDomain = domain
        self._password = password
        self._token = token
        self._loginkey = loginkey
        self._socket_open = asyncio.Event()
        self._inflight = set()
        self._file_tunnels = {}
        self._ignore_ssl = ignore_ssl
        self.auto_reconnect = auto_reconnect
        if user_agent_header:
            self.user_agent_header = user_agent_header
        else:
            self.user_agent_header = default_user_agent_header

        self._eventer = util.Eventer()

        self.initialized = asyncio.Event()
        self._initialization_err = None

        self._main_loop_task = asyncio.create_task(self._main_loop())
        self._main_loop_error = None

        self._server_info = {}
        self._user_info = {}
        self._command_id = 0
        self.alive = False
        self.closed = asyncio.Event()

        self._message_queue = asyncio.Queue()
        self._send_task = None
        self._listen_task = None
        self._ssl_context = None
        if self._ignore_ssl:
            self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE

    async def _main_loop(self):
        try:
            options = {}
            if self._ssl_context is not None:
                options["ssl"] = self._ssl_context

            headers = websockets.datastructures.Headers()

            if (self._password):
                token = self._token if self._token else b""
                headers['x-meshauth'] = (base64.b64encode(self._user.encode()) + b',' + base64.b64encode(self._password.encode()) + token).decode()


            options["additional_headers"] = headers
            async for websocket in websockets.asyncio.client.connect(self.url, proxy=self._proxy, process_exception=util._process_websocket_exception, max_size=None, user_agent_header=self.user_agent_header, **options):
                self.alive = True
                self._socket_open.set()
                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._listen_data_task(websocket))
                        tg.create_task(self._send_data_task(websocket))
                except* websockets.ConnectionClosed as e:
                    self._socket_open.clear()
                    if not self.auto_reconnect:
                        raise

        except* Exception as eg:
            self.alive = False
            self._socket_open.clear()
            self._main_loop_error = eg
            self.closed.set()
            self.initialized.set()

    @classmethod
    async def create(cls, *args, **kwargs):
        s = cls(*args, **kwargs)
        await s.initialized.wait()
        return s

    async def _send_data_task(self, websocket):
        while True:
            message = await self._message_queue.get()
            await websocket.send(message)

    async def _listen_data_task(self, websocket):
        async for message in websocket:
            await self._eventer.emit("raw", message)
            # Meshcentral does pong wrong and breaks our parsing, so fix it here. This is fixed now, but we want compatibility with old versions.
            if message == '{action:"pong"}':
                message = '{"action":"pong"}'

            # Can't process non-json data, don't even try
            try:
                data = json.loads(message)
            except SyntaxError:
                continue
            action = data.get("action", None)
            await self._eventer.emit("server_event", data)
            if action == "close":
                if data.get("cause", None) == "noauth":
                    raise exceptions.ServerError("Invalid Auth")
            if action == "userinfo":
                self._user_info = data["userinfo"]
                self.initialized.set()

            if action == "serverinfo":
                self._currentDomain = data["serverinfo"]["domain"]
                self._server_info = data["serverinfo"]
            id = data.get("responseid", data.get("tag", None))
            if id:
                await self._eventer.emit(id, data)
            else:
                # Some events don't user their response id, they just have the action. This should be fixed eventually.
                # Broken commands include:
                #      meshes
                #      nodes
                #      getnetworkinfo
                #      lastconnect
                #      getsysinfo
                # console.log(`emitting ${data.action}`)
                await self._eventer.emit(action, data)

    def _get_command_id(self):
        self._command_id = (self._command_id+1)%(2**32-1)
        return self._command_id

    async def close(self):
        try:
            await asyncio.gather(*[tunnel.close() for name, tunnel in self._file_tunnels.items()])
        finally:
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
            except asyncio.CancelledError:
                pass

    @util._check_socket
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_t, exc_v, exc_tb):
        await self.close()

    @util._check_socket
    async def _send_command(self, data, name, timeout=None):
        id = f"meshctrl_{name}_{self._get_command_id()}"
        # This fixes a very theoretical bug with hash colisions in the case of an infinite int of requests. Now the bug will only happen if there are currently 2**32-1 of the same type of request going out at the same time
        while id in self._inflight:
            id = f"meshctrl_{name}_{self._get_command_id()}"

        self._inflight.add(id)
        responded = asyncio.Event()
        response = None
        async def _(data):
            self._inflight.remove(id)
            nonlocal response
            response = data
            responded.set()
        self._eventer.once(id, _)
        await self._message_queue.put(json.dumps(data | {"tag": id, "responseid": id}))
        await asyncio.wait_for(responded.wait(), timeout=timeout)
        if isinstance(response, Exception):
            raise response
        return response

    @util._check_socket
    async def _send_command_no_response_id(self, data, action_override=None, timeout=None):
        responded = asyncio.Event()
        response = None
        async def _(data):
            nonlocal response
            response = data
            responded.set()
        self._eventer.once(action_override if action_override is not None else data["action"], _)
        await self._message_queue.put(json.dumps(data))
        await asyncio.wait_for(responded.wait(), timeout=timeout)
        if isinstance(response, Exception):
            raise response
        return response

    @util._check_socket
    async def server_info(self):
        """
        Get server information

        Returns:
           (dict) Server info
        """
        return self._server_info

    @util._check_socket
    async def user_info(self):
        """
        Get user information

        Returns:
           (dict) User info
        """
        return self._user_info
    
    async def ping(self, timeout=None):
        '''
        Ping the server. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict: {"action": "pong"}

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error from server
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        data = await self._send_command_no_response_id({"action": "ping"}, action_override="pong", timeout=timeout)
        return data

    async def list_device_groups(self, timeout=None):
        '''
        Get device groups. Only returns meshes to which the logged in user has access

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[~meshctrl.mesh.Mesh]: List of meshes

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error from server
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        data = await self._send_command({"action": "meshes"}, "list_device_groups", timeout=timeout)
        return [mesh.Mesh(m["_id"], self, **m) for m in data["meshes"]]


    async def send_invite_email(self, group, email, name=None, message=None, meshid=None, timeout=None):
        '''
        Send an invite email for a group or mesh
        TODO: This has no tests for it

        Args:
            group (str): Name of mesh to which to invite email
            email (str): Email of user to invite
            name (str): User's name. For display purposes.
            message (str): Message to send to user in invite email
            meshid (str): ID of mesh which to invite user. Overrides "group"
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        op = { 
            "action": 'inviteAgent',
            "email": email,
            "name": '',
            "os": '0'
        }
        if meshid:
            op["meshid"] = meshid
        elif group:
            op["meshname"] = group
        if name:
            op["name"] = name
        if message:
            op["msg"] = message
        data = await self._send_command(op, "send_invite_email", timeout=timeout)
        if ("result" in data and data["result"].lower() != "ok"):
            raise exceptions.ServerError(data["result"])
        return True

    async def generate_invite_link(self, group, hours, flags=None, meshid=None, timeout=None):
        '''
        Generate an invite link for a group or mesh
        TODO: This has no tests for it

        Args:
            group (str): Name of group to add
            hours (int): Hours until link expires
            flags (~meshctrl.constants.MeshRights|~meshctrl.constants.DeviceRights): Bitwise flags representing rights for device/mesh
            meshid (str): ID of mesh which to invite user. Overrides "group"
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict: Invite link information

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        op = { 
            "action": 'createInviteLink',
            "expire": hours,
            "flags": 0
        }
        if meshid:
            op["meshid"] = meshid
        elif group:
            op["meshname"] = group
        if flags != None:
            op["flags"] = flags
        data = await self._send_command(op, "generate_invite_link", timeout=timeout)
        if ("result" in data and data["result"].lower() != "ok"):
            raise exceptions.ServerError(data["result"])
        del data["tag"]
        del data["responseid"]
        del data["action"]
        return data

    async def list_users(self, timeout=None):
        '''
        List users on server. Admin Only.

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[~meshctrl.types.ListUsersResponseItem]: List of users

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        data = await self._send_command({"action": "users"}, "list_users", timeout=timeout)
        if ("result" in data and data["result"].lower() != "ok"):
            raise exceptions.ServerError(data["result"])
        return data["users"]

    async def list_user_sessions(self, timeout=None):
        '''
        Get list of connected users. Admin Only.

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict[str, int]: Number of sessions per user

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        return (await self._send_command({"action": "wssessioncount"}, "list_user_sessions", timeout=timeout))["wssessions"]

    
    async def list_devices(self, details=False, group=None, meshid=None, timeout=None):
        '''
        Get devices to which the user has access.
        Different options will fill different properties in the resultant device objects, based on what is returned from meshcentral. Documenting these changes is beyond the scope of this documentation.

        Args:
            details (bool): Get device details, overrides group and meshid
            group (str): Get devices from specific group by name. Overrides meshid
            meshid (str): Get devices from specific group by id
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[~meshctrl.device.Device]: List of nodes

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        tasks = []
        async with asyncio.TaskGroup() as tg:
            if details:
                tasks.append(tg.create_task(self._send_command_no_response_id({"action": "getDeviceDetails", "type":"json"}, timeout=timeout)))
            elif group:
                tasks.append(tg.create_task(self._send_command({ "action": 'nodes', "meshname": group}, "list_devices", timeout=timeout)))
            elif meshid:
                tasks.append(tg.create_task(self._send_command({ "action": 'nodes', "meshid": meshid}, "list_devices", timeout=timeout)))
            else:
                tasks.append(tg.create_task(self._send_command({ "action": 'meshes' }, "list_devices", timeout=timeout)))
                tasks.append(tg.create_task(self._send_command({ "action": 'nodes' }, "list_devices", timeout=timeout)))

        res0 = tasks[0].result()
        if "result" in res0:
            raise exceptions.ServerError(res0["result"])
        if details:
            nodes = res0["data"]
            # Accept any number of nested strings, meshcentral is odd
            while True:
                try:
                    nodes = json.loads(nodes)
                except TypeError:
                    break

            for node in nodes:
                if node["node"].get("meshid", None):
                    node["node"]["mesh"] = mesh.Mesh(node["node"].get("meshid"), self)
                if "lastConnect" in node and isinstance(node["lastConnect"], dict):
                    node["node"]["lastconnect"] = node["lastConnect"].get("time")
                    node["node"]["lastaddr"] = node["lastConnect"].get("addr")
                    del node["lastConnect"]
                details = {}
                for key, val in node.items():
                    if key != "node":
                        details[key] = val
                node["node"]["details"] = details
            return [device.Device(n["node"]["_id"], self, **n["node"]) for n in nodes]
        if group or meshid:
            nodes = []
            for _meshid, node_list in res0["nodes"].items():
                for node in node_list:
                    node["meshid"] = meshid
                    if meshid:
                        node["mesh"] = mesh.Mesh(_meshid, self)
                    if group:
                        node["groupname"] = group
                    nodes.append(node)
            return [device.Device(n["_id"] , self, **n) for n in nodes]
        # if "meshes" not in res0 or not res0["meshes"]:
        #     return tasks[1].result()["nodes"]

        xmeshes = {}
        nodes = []
        for _mesh in res0["meshes"]:
            xmeshes[_mesh["_id"]] = _mesh
        for meshid, devicesInMesh in tasks[1].result()["nodes"].items():
            for _device in devicesInMesh:
                _device["meshid"] = meshid; # Add device group id
                if xmeshes and meshid in xmeshes and "name" in xmeshes[meshid]:
                    _device["groupname"] = xmeshes[meshid]["name"] # Add device group name
                nodes.append(_device);
        for node in nodes:
            if node.get("meshid", None):
                node["mesh"] = mesh.Mesh(node.get("meshid"), self)
        return [device.Device(n["_id"], self, **n) for n in nodes]

    async def raw_messages(self):
        '''
        Listen to raw messages from the server. These will be strings that have not been parsed at all. Consider this an emergency fallback if meshcentral sends something odd. You will get every message from the websocket.

        Returns:
            generator(data): A generator which will generate every message the server sends
        '''
        event_queue = asyncio.Queue()
        async def _(data):
            await event_queue.put(data)
        self._eventer.on("raw", _)
        try:
            while True:
                data = await event_queue.get()
                yield data
        finally:
            self._eventer.off("raw", _)

    async def events(self, filter=None):
        '''
        Listen to events from the server

        Args:
            filter (dict): dict to filter events with. Only trigger for events that deep-match this dict. Use sets for "array.contains" and arrays for equality of lists.

        Returns:
            generator(data): A generator with the events that match the given filter, or all events if no filter is given
         '''
        event_queue = asyncio.Queue()
        async def _(data):
            await event_queue.put(data)
        self._eventer.on("server_event", _)
        try:
            while True:
                data = await event_queue.get()
                if filter and not util.compare_dict(filter, data):
                    continue
                yield data
        finally:
            self._eventer.off("server_event", _)

    async def list_events(self, userid=None, nodeid=None, limit=None, timeout=None):
        '''
        List events visible to the currect user

        Args:
            userid (str): Filter by user. Overrides nodeid. Only works for admin, otherwise ignored.
            nodeid (str): Filter by node
            limit (int): Limit to the N most recent events
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[dict]: List of events

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        try:
            if (limit < 1):
                limit = None
        except:
            limit = None

        cmd = None;
        if userid:
            cmd = { "action": 'events', "userid": userid }
        elif (nodeid):
            cmd = { "action": 'events', "nodeid": nodeid }
        else:
            cmd = { "action": 'events' }

        if limit:
            cmd["limit"] = limit

        data = await self._send_command(cmd, "list_events", timeout=timeout)
        return data["events"]

    async def list_login_tokens(self, timeout=None):
        '''
        List login tokens for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[~meshctrl.types.RetrievedLoginToken]: List of tokens

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        return (await self._send_command_no_response_id({"action": "loginTokens"}, timeout=timeout))["loginTokens"]

    async def add_login_token(self, name, expire=None, timeout=None):
        '''
        Create login token for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            name (str): Name of token
            expire (int): Minutes until expiration. 0 or None for no expiration.
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            ~meshctrl.types.LoginToken: Created token

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        cmd = { "action": 'createLoginToken', "name": name, "expire": 0 if not expire else expire }
        data = await self._send_command_no_response_id(cmd, timeout=timeout)
        del data["action"]
        return data

    async def remove_login_token(self, names, timeout=None):
        '''
        Remove login token for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            name (str): Name of token or token username
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[~meshctrl.types.RetrievedLoginToken]: List of remaining tokens

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''

        if isinstance(names, str):
            names = [names]

        realnames = []
        tokens = await self.list_login_tokens()
        for name in names:
            if not name.startswith("~"):
                for token in tokens:
                    if token["name"] == name:
                        name = token["tokenUser"]
                        break
            realnames.append(name)
        return (await self._send_command_no_response_id({ "action": 'loginTokens', "remove": realnames }, timeout=timeout))["loginTokens"]

    async def add_user(self, name, password=None, randompass=False, domain=None, email=None, emailverified=False, resetpass=False, realname=None, phone=None, rights=None, timeout=None):
        '''
        Add a new user

        Args:
            name (str): username
            password (str): user's starting password
            randompass (bool): Generate a random password for the user. Overrides password
            domain (str): Domain to which to add the user
            email (str): User's email address
            emailverified (bool): Pre-verify the user's email address
            resetpass (bool): Force the user to reset their password on first login
            realname (str): User's real name
            phone (str): User's phone number
            rights (~meshctrl.constants.UserRights): Bitwise mask of user's rights on the server
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if randompass:
            password = util._get_random_amt_password()
        op = { "action": 'adduser', "username": name, "pass": password };
        if email:
            op["email"] = email
            if emailverified:
                op["emailVerified"] = True
        if resetpass:
            op["resetNextLogin"] = True
        if rights is not None:
            op["siteadmin"] = rights
        if domain:
            op["domain"] = domain
        elif self._domain:
            op["domain"] = self._domain

        if isinstance(phone, str):
            op["phone"] = phone
        if isinstance(realname, str):
            op["realname"] = realname

        data = await self._send_command(op, "add_user", timeout=timeout)
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def edit_user(self, userid, domain=None, email=None, emailverified=False, resetpass=False, realname=None, phone=None, rights=None, timeout=None):
        '''
        Edit an existing user

        Args:
            userid (str): Unique userid
            domain (str): Domain to which to add the user
            email (str): User's email address
            emailverified (bool): Verify or unverify the user's email address
            resetpass (bool): Force the user to reset their password on next login
            realname (str): User's real name
            phone (str): User's phone number
            rights (~meshctrl.constants.UserRights): Bitwise mask of user's rights on the server
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if (domain is not None) and ("/" not in userid):
            userid = f"user/{domain}/{userid}"
        elif (self._domain is not None) and ("/" not in userid):
            userid = f"user/{self._domain}/{userid}"

        op = { "action": 'edituser', "userid": userid}
        if email is not None:
            op["email"] = email
            if emailverified:
                op["emailVerified"] = True

        if resetpass:
            op["resetNextLogin"] = True
        if rights is not None:
            op["siteadmin"] = rights
        if domain:
            op["domain"] = domain
        elif self._domain:
            op["domain"] = self._domain
        if phone is True:
            op["phone"] = ''
        if isinstance(phone, str):
            op["phone"] = phone
        if isinstance(realname, str):
            op["realname"] = realname
        if realname is True:
            op["realname"] = ''
        data = await self._send_command(op, "edit_user", timeout=timeout) 
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def remove_user(self, userid, domain=None, timeout=None):
        '''
        Remove an existing user

        Args:
            userid (str): Unique userid
            domain (str): Domain to which to add the user
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise
        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if (domain is not None) and ("/" not in userid):
            userid = f"user/{domain}/{userid}"
        elif (self._domain is not None) and ("/" not in userid):
            userid = f"user/{self._domain}/{userid}"

        data = await self._send_command({ "action": 'deleteuser', "userid": userid }, "remove_user", timeout=timeout)
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def add_user_group(self, name, domain=None, description=None, timeout=None):
        '''
        Create a new user group

        Args:
            name (str): Name of usergroup
            domain (str): Domain to which to add the user
            description (str): Description of user group
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            ~meshctrl.user_group.UserGroup: New user group

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        op = { "action": 'createusergroup', "name": name, "desc": description };
        if domain is not None:
            op["domain"] = self._domain
        elif self._domain is not None:
            op["domain"] = self._domain
        data = await self._send_command(op, "add_user_group", timeout=timeout)
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])

        del data["action"]
        del data["responseid"]
        del data["result"]
        ugrpid = data["ugrpid"]
        del data["ugrpid"]
        return user_group.UserGroup(ugrpid, self, name=name, description=description, domain=domain, **data)

    async def remove_user_group(self, groupid, domain=None, timeout=None):
        '''
        Remove an existing user group

        Args:
            userid (str): Unique userid
            domain (str): Domain to which to add the user
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if (domain is not None) and ("/" not in groupid):
            userid = f"ugrp/{domain}/{userid}"
        elif (self._domain is not None) and ("/" not in groupid):
            userid = f"ugrp/{self._domain}/{userid}"

        if (not groupid.startswith("ugrp/")):
            groupid = f"ugrp//{groupid}"
        data = await self._send_command({ "action": 'deleteusergroup', "ugrpid": groupid }, "remove_user_group", timeout=timeout)
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def list_user_groups(self, timeout=None):
        '''
        Get user groups. Admin will get all user groups, otherwise get limited user groups

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[~meshctrl.user_group.UserGroup]: List of groups. If you are not a member, you'l just get the names and ids.

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        r = await self._send_command({"action": "usergroups"}, "list_user_groups", timeout=timeout)
        groups = []
        for key, val in r["ugroups"].items():
            val["_id"] = key
            groups.append(user_group.UserGroup(key, self, **val))
        return groups

    async def add_users_to_user_group(self, usernames, groupid, domain=None, timeout=None):
        '''
        Add user(s) to an existing user group. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            usernames (str|list[str]): Unique user name(s). This API will not work with the full user ID, but we will try to turn it into something that makes sense.
            groupid (str): Group to add the given user to
            domain (str): Domain containing the group
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict[str, ~meshctrl.types.AddUsersToUserGroupResponse]: List of users that were successfully added. str is username.

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(usernames, str):
            usernames = [usernames]
        _new = []
        for username in usernames:
            _new.append(username.split("/")[-1])
        usernames = _new


        if (domain is not None) and ("/" not in groupid):
            groupid = f"ugrp/{domain}/{groupid}"
        elif (self._domain is not None) and ("/" not in groupid):
            groupid = f"ugrp/{self._domain}/{groupid}"

        if (not groupid.startswith("ugrp/")):
            groupid = f"ugrp//{groupid}"

        result = {u: {"success": False, "done": False, "message": None} for u in usernames}
        tasks = []
        def check_results():
            for key, val in result.items():
                if not val["done"]:
                    break
            else:
                return True
            return False
        async def _(tg):
            async for event in self.events({"event": {"etype":"ugrp"}}):
                for username in event["event"]["msgArgs"][0]:
                    result[username]["success"] = True
                    result[username]["done"] = True
                if check_results():
                    tasks[1].cancel()
                    return

        async def __(tg):
            async for event in self.events({"action": "msg", "type":"notify", "tag": "ServerNotify"}):
                for username in usernames:
                    if username in event["value"]:
                        result[username]["success"] = False
                        result[username]["message"] = event["value"]
                        result[username]["done"] = True
                if check_results():
                    tasks[0].cancel()
                    return


        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(asyncio.wait_for(_(tg), timeout=timeout)))
            tasks.append(tg.create_task(asyncio.wait_for(__(tg), timeout=timeout)))
            tasks.append(tg.create_task(self._send_command({ "action": 'addusertousergroup', "ugrpid": groupid, "usernames": usernames}, "add_users_to_user_group", timeout=timeout)))


        res = tasks[2].result()
        if "result" in res and res["result"] != "ok":
            raise exceptions.ServerError(res.result)
        return {key: {"success": val["success"], "message": val["message"]} for key,val in result.items()}

    async def remove_user_from_user_group(self, userid, groupid, domain=None, timeout=None):
        '''
        Remove user from an existing user group

        Args:
            userid (str): Unique user id
            groupid (str): Group to remove the given user from
            domain (str): Domain containing the group
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if (domain is not None) and ("/" not in groupid):
            groupid = f"ugrp/{domain}/{groupid}"
        elif (self._domain is not None) and ("/" not in groupid):
            groupid = f"ugrp/{self._domain}/{groupid}"

        if (not groupid.startswith("ugrp/")):
            groupid = f"ugrp//{groupid}"

        data = await self._send_command({ "action": 'removeuserfromusergroup', "ugrpid": groupid, "userid": userid }, "remove_from_user_group", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def add_users_to_device(self, userids, nodeid, rights=None, timeout=None):
        '''
        Add a user to an existing node

        Args:
            userids (str|list[str]): Unique user id(s)
            nodeid (str): Node to add the given user to
            rights (~meshctrl.constants.DeviceRights): Bitwise mask for the rights on the given device
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(userids, str):
            userids = [userids]

        userids = [f"user//{u}" if  not u.startswith("user//") else u for u in userids]
        if rights is None:
            rights = 0

        data = await self._send_command({ "action": 'adddeviceuser', "nodeid": nodeid, "userids": userids, "rights": rights}, "add_users_to_device", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def remove_users_from_device(self, nodeid, userids, timeout=None):
        '''
        Remove users from an existing node

        Args:
            nodeid (str): Node to remove the given users from
            userids (str|list[str]): Unique user id(s)
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(userids, str):
            userids = [userids]

        userids = [f"user//{u}" if  not u.startswith("user//") else u for u in userids]

        data = await self._send_command({ "action": 'adddeviceuser', "nodeid": nodeid, "usernames": userids, "rights": 0, "remove": True }, "remove_users_from_device", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def remove_devices(self, nodeids, timeout=None):
        '''
        Remove device(s) from MeshCentral

        Args:
            nodeids (str|list[str]): nodeid(s) of the device(s) that have to be removed
            timeout (int): duration in seconds to wait for a response before throwing an error
        
        Returns:
            bool: True on success, raise otherwise

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(nodeids, str):
            nodeids = [nodeids]

        data = await self._send_command({ "action": 'removedevices', "nodeids": nodeids}, "remove_devices", timeout=timeout)
        
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def add_device_group(self, name, description="", amtonly=False, features=0, consent=0, timeout=None):
        '''
        Create a new device group

        Args:
            name (str): Name of device group
            description (str): Description of device group
            amtonly (bool): 
            features (~meshctrl.constants.MeshFeatures): Bitwise features to enable on the group
            consent (~meshctrl.constants.ConsentFlags): Bitwise consent flags to use for the group
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            ~meshctrl.mesh.Mesh: Newly created device group.

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        op = { "action": 'createmesh', "meshname": name, "meshtype": 2 };
        if description:
            op["desc"] = description
        if amtonly:
            op["meshtype"] = 1
        if features:
            op["flags"] = features
        if consent:
            op["consent"] = consent

        data = await self._send_command(op, "add_device_group", timeout=timeout)
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])

        del data["action"]
        del data["responseid"]
        del data["result"]
        meshid = data["meshid"]
        del data["meshid"]
        data["name"] = name
        data["description"] = description
        return mesh.Mesh(meshid, self, **data)

    async def remove_device_group(self, meshid, isname=False, timeout=None):
        '''
        Remove an existing device group

        Args:
            meshid (str): Unique id of device group
            isname (bool): treat "meshid" as a name instead of an id
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        op = { "action": 'deletemesh', "meshid": meshid};
        if isname:
            op["meshname"] = meshid
            del op["meshid"]

        data = await self._send_command(op, "remove_device_group", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def edit_device_group(self, meshid, isname=False, name=None, description=None, flags=None, consent=None, invite_codes=None, backgroundonly=False, interactiveonly=False, timeout=10):
        '''
        Edit an existing device group. WARNING: This command will just hang if you do not have permissions. Because of this, timeout is defaulted to 10 seconds. Be wary if you remove the timeout.

        Args:
            meshid (str): Unique id of device group
            isname (bool): treat "meshid" as a name instead of an id
            name (str): New name for group
            description (str): New description
            flags (~meshctrl.constants.MeshFeatures): Features to enable on the group
            consent (~meshctrl.constants.ConsentFlags): Which consent flags to use for the group
            invite_codes (list[str]|True): Create new invite codes. If True, pass `"*"`. I don't know what this means.
            backgroundonly (bool): Flag for invite codes
            interactiveonly (bool): Flag for invite codes
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        op = { "action": 'editmesh', "meshid": meshid};
        if isname:
            op["meshidname"] = meshid
            del op["meshid"]

        if name is not None:
            op["meshname"] = name
        if description is not None:
            op["desc"] = description
        if invite_codes == True:
            op["invite"] = "*"
        elif invite_codes is not None:
            op["invite"] = { "codes": invite_codes, "flags": 0 }
            if backgroundonly:
                op["invite"]["flags"] = 2
            elif interactiveonly:
                op["invite"]["flags"] = 1

        if flags is not None:
            op["flags"] = flags

        if consent is not None:
            op["consent"] = consent

        data = await self._send_command(op, "edit_device_group", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def move_to_device_group(self, nodeids, meshid, isname=False, timeout=None):
        '''
        Move a device from one group to another

        Args:
            nodeids (str|list[str]): Unique node id(s)
            meshid (str): Unique mesh id
            isname (bool): treat "meshid" as a name instead of an id
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(nodeids, str):
            nodeids = [nodeids]
        op = { "action": 'changeDeviceMesh', "nodeids": nodeids, "meshid": meshid };
        if isname:
            op["meshname"] = meshid
            del op["meshid"]

        data = await self._send_command(op, "move_to_device_group", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def add_users_to_device_group(self, userids, meshid, isname=False, rights=0, timeout=None):
        '''
        Add a user to an existing mesh

        Args:
            userids (str|list[str]): Unique user id(s)
            meshid (str): Mesh to add the given user to
            isname (bool): Read meshid as a name rather than an id
            rights (~meshctrl.constants.MeshRights): Bitwise mask for the rights on the given mesh
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict[str, ~meshctrl.types.AddUsersToDeviceGroupResponse]: Dict showing which were added correctly and which were not, along with their result messages. str is userid to map response.

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(userids, str):
            userids = [userids]
        original_ids = userids
        userids = [f"user//{u}" if  not u.startswith("user//") else u for u in userids]
        op = { "action": 'addmeshuser', "userids": userids, "meshadmin": rights, "meshid": meshid };
        if isname:
            op["meshname"] = meshid
            del op["meshid"]

        data = await self._send_command(op, "add_user_to_device_group", timeout=timeout)
        results = data["result"].split(",")
        out = {}
        for i, result in enumerate(results):
            if i >= len(original_ids):
                out["all"] = result
            else:
                out[original_ids[i]] = {
                    "success": result.startswith("Added user"),
                    "message": result
                }
        return out

    async def remove_users_from_device_group(self, userids, meshid, isname=False, timeout=None):
        '''
        Remove users from an existing mesh

        Args:
            userids (str|list[str]): Unique user id(s)
            meshid (str): Mesh to add the given user to
            isname (bool): Read meshid as a name rather than an id
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict[str, ~meshctrl.types.AddUsersToDeviceGroupResponse]: Dict showing which were removed correctly and which were not, along with their result messages. str is userid to map response.

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        requests = []
        id_obj = {"meshid": meshid}
        if isname:
            id_obj["meshname"] = meshid
            del id_obj["meshid"]

        if isinstance(userids, str):
            userids = [userids]

        tasks = []
        async with asyncio.TaskGroup() as tg:
            for userid in userids:
                tasks.append(tg.create_task(self._send_command({ "action": 'removemeshuser', "userid": userid } | id_obj, "remove_users_from_device_group", timeout=timeout)))

        out = {}
        for i, task in enumerate(tasks):
            result = task.result()
            if result.get("result", "") == "ok":
                out[userids[i]] = {"success": True}
            else:
                out[userids[i]] = {"success": False}
            out[userids[i]]["message"] = result["result"]
        return out

    async def broadcast(self, message, userid=None, timeout=None):
        '''
        Broadcast a message to all users or a single user
        TODO: This has no tests for it

        Args:
            message (str): Message to broadcast
            userid (str): Optional user to which to send the message
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        op = { "action": 'userbroadcast', "msg": message };
        if userid:
            op["userid"] = userid

        data = await self._send_command(op, "broadcast", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def device_info(self, nodeid, timeout=None):
        '''
        Get all info for a given device. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeid (str): Unique id of desired node
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            ~meshctrl.device.Device: Object representing the state of the device

        Raises:    
            ValueError: `Invalid device id` if device is not found
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        tasks = []
        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(self._send_command({ "action": 'nodes' }, "device_info", timeout=timeout)))
            tasks.append(tg.create_task(self._send_command_no_response_id({ "action": 'getnetworkinfo', "nodeid": nodeid }, timeout=timeout)))
            tasks.append(tg.create_task(self._send_command_no_response_id({ "action": 'lastconnect', "nodeid": nodeid }, timeout=timeout)))
            tasks.append(tg.create_task(self._send_command({ "action": 'getsysinfo', "nodeid": nodeid, "nodeinfo": True }, "device_info", timeout=timeout)))
            tasks.append(tg.create_task(self.list_device_groups(timeout=timeout)))

        nodes, network, lastconnect, sysinfo, meshes = (_.result() for _ in tasks)

        
        node = None
        if sysinfo is not None and sysinfo.get("node", None):
            # Node information came with system information
            node = sysinfo.get("node", None)
            for meshid, _nodes in nodes["nodes"].items():
                for _mesh in meshes:
                    if _mesh.meshid == meshid:
                        break
                else:
                    break
                if meshid == node["meshid"]:
                    node["mesh"] = _mesh
        else:
            # This device does not have system information, get node information from the nodes list.
            for meshid, _nodes in nodes["nodes"].items():
                for _mesh in meshes:
                    if _mesh.meshid == meshid:
                        break
                else:
                    _mesh = None
                for _node in _nodes:
                    if nodeid in _node["_id"]:
                        node = _node
                        node["meshid"] = meshid
                        if _mesh is not None:
                            node["mesh"] = _mesh
                        break
                else:
                    continue
                break
        if node is None:
            raise ValueError("Invalid device id")
        if lastconnect is not None:
            node["lastconnect"] = lastconnect["time"]
            node["lastaddr"] = lastconnect["addr"]
        if node.get("meshid", None) and "mesh" not in node:
            node["mesh"] = mesh.Mesh(node["meshid"], self)
        return device.Device(node["_id"], self, **node)
        
    async def edit_device(self, nodeid, name=None, description=None, tags=None, icon=None, consent=None, timeout=None):
        '''
        Edit properties of an existing device

        Args:
            nodeid (str): Unique id of desired node
            name (str): New name for device
            description (str): New description for device
            tags (str|list[str]]): New tags for device
            icon (~meshctrl.constants.Icon): New icon for device
            consent (~meshctrl.constants.ConsentFlags): New consent flags for device
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        op = { "action": 'changedevice', "nodeid": nodeid };
        if name is not None:
            op["name"] = name
        if description is not None:
            op["desc"] = description
        if tags is not None:
            op["tags"] = tags
        if icon is not None:
            op["icon"] = icon
        if consent is not None:
            op["consent"] = consent

        data = await self._send_command(op, "edit_device", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        return True

    async def run_command(self, nodeids, command, powershell=False, runasuser=False, runasuseronly=False, ignore_output=False, timeout=None):
        '''
        Run a command on any number of nodes. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeids (str|list[str]): Unique ids of nodes on which to run the command
            command (str): Command to run
            powershell (bool): Use powershell to run command. Only available on Windows.
            runasuser (bool): Attempt to run as a user instead of the root permissions given to the agent. Fall back to root if we cannot.
            ignore_output (bool): Don't bother trying to get the output. Every device will return an empty string for its result.
            runasuseronly (bool): Error if we cannot run the command as the logged in user.
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict[str, ~meshctrl.types.RunCommandResponse]: Dict containing mapped output of the commands by device

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            ValueError: `Invalid device id` if device is not found
            asyncio.TimeoutError: Command timed out
         '''
        runAsUser = 0
        if runasuser:
            runAsUser = 1
        if runasuseronly:
            runAsUser = 2
        if isinstance(nodeids, str):
            nodeids = [nodeids]

        def match_nodeid(id, ids):
            for nid in ids:
                if (nid == id):
                    return nid
                if (nid[6:] == id):
                    return nid
                if (f"node//{nid}" == id):
                    return nid

        result = {n: {"complete": False, "result": [], "command": command} for n in nodeids}
        async def _console():
            async for event in self.events({"action": "msg", "type": "console"}):
                node = match_nodeid(event["nodeid"], nodeids)
                if node:
                    if event["value"] == "Run commands completed.":
                        result.setdefault(node, {})["complete"] = True
                        if all(_["complete"] for key, _ in result.items()):
                            break
                        continue
                    elif (event["value"].startswith("Run commands")):
                        continue
                    result[node]["result"].append(event["value"])
            

        async def __(command, tg, tasks):
            data = await self._send_command(command, "run_command", timeout=timeout)

            if data.get("type", None) != "runcommands" and data.get("result", "ok").lower() != "ok":
                raise exceptions.ServerError(data["result"])
            elif data.get("type", None) != "runcommands" and data.get("result", "ok").lower() == "ok":
                expect_response = False
                console_task = tg.create_task(asyncio.wait_for(_console(), timeout=timeout))
                if not ignore_output:
                    userid = (await self.user_info())["_id"]
                    for n in nodeids:
                        device_info = await self.device_info(n, timeout=timeout)
                        try:
                            permissions = device_info.mesh.links.get(userid, {}).get("rights",constants.DeviceRights.norights)\
                            # This should work for device rights, but it only seems to work for mesh rights. Not sure why, but I can't get the events to show up when the user only has individual device rights
                            # |device_info.get("links", {}).get(userid, {}).get("rights", constants.DeviceRights.norights)
                            # If we don't have agentconsole rights, we won't be able te read the output, so fill in blanks on this node
                            if not permissions&constants.DeviceRights.agentconsole:
                                result[n]["complete"] = True
                            else:
                                expect_response = True
                        except AttributeError:
                            result[n]["complete"] = True
                if expect_response:
                    tasks.append(console_task)
                else:
                    console_task.cancel()
            elif data.get("type", None) == "runcommands" and not ignore_output:
                # Returns True when all results are in, Falsey otherwise
                def _parse_event(event):
                    node = match_nodeid(event["nodeid"], nodeids)
                    if node:
                        result.setdefault(node, {})["complete"] = True
                        result[node]["result"].append(event["result"])
                        if all(_["complete"] for key, _ in result.items()):
                            return True
                if data is not None:
                    if _parse_event(data):
                        return
                async for event in self.events({"action": "msg", "type": "runcommands", "responseid": data["responseid"]}):
                    if _parse_event(event):
                        break

        tasks = []
        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(__({ "action": 'runcommands', "nodeids": nodeids, "type": (2 if powershell else 0), "cmds": command, "runAsUser": runAsUser, "reply": not ignore_output}, tg, tasks)))

        return {n: v | {"result": "".join(v["result"])} for n,v in result.items()}

    async def run_console_command(self, nodeids, command, powershell=False, runasuser=False, runasuseronly=False, ignore_output=False, timeout=None):
        '''
        Run a mesh console command on any number of nodes. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeids (str|list[str]): Unique ids of nodes on which to run the command
            command (str): Command to run
            ignore_output (bool): Don't bother trying to get the output. Every device will return an empty string for its result.
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict[str, ~meshctrl.types.RunCommandResponse]: Dict containing mapped output of the commands by device

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            ValueError: `Invalid device id` if device is not found
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(nodeids, str):
            nodeids = [nodeids]

        def match_nodeid(id, ids):
            for nid in ids:
                if (nid == id):
                    return nid
                if (nid[6:] == id):
                    return nid
                if (f"node//{nid}" == id):
                    return nid

        result = {n: {"complete": False, "result": [], "command": command} for n in nodeids}
        async def _console():
            async for event in self.events({"action": "msg", "type": "console"}):
                # We can pick up run commands here sometimes if they are run in quick succession. Try to avoid that.
                if (not event["value"].startswith("Run commands")):
                    node = match_nodeid(event["nodeid"], nodeids)
                    if node:
                        result[node]["result"].append(event["value"])
                        result.setdefault(node, {})["complete"] = True
                        if all(_["complete"] for key, _ in result.items()):
                            break
        async def __(command, tg, tasks):
            data = await self._send_command(command, "run_console_command", timeout=timeout)

            if data.get("type", None) != "runcommands" and data.get("result", "ok").lower() != "ok":
                raise exceptions.ServerError(data["result"])
            elif data.get("type", None) != "runcommands" and data.get("result", "ok").lower() == "ok":
                expect_response = False
                console_task = tg.create_task(asyncio.wait_for(_console(), timeout=timeout))
                if not ignore_output:
                    userid = (await self.user_info())["_id"]
                    for n in nodeids:
                        device_info = await self.device_info(n, timeout=timeout)
                        try:
                            permissions = device_info.mesh.links.get(userid, {}).get("rights",constants.DeviceRights.norights)\
                            # This should work for device rights, but it only seems to work for mesh rights. Not sure why, but I can't get the events to show up when the user only has individual device rights
                            # |device_info.get("links", {}).get(userid, {}).get("rights", constants.DeviceRights.norights)
                            # If we don't have agentconsole rights, we won't be able te read the output, so fill in blanks on this node
                            if not permissions&constants.DeviceRights.agentconsole:
                                result[n]["complete"] = True
                            else:
                                expect_response = True
                        except AttributeError:
                            result[n]["complete"] = True
                if expect_response:
                    tasks.append(console_task)
                else:
                    console_task.cancel()

        tasks = []
        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(__({ "action": 'runcommands', "nodeids": nodeids, "type": 4, "cmds": command}, tg, tasks)))

        return {n: v | {"result": "".join(v["result"])} for n,v in result.items()}

    def shell(self, nodeid):
        '''
        Get a terminal shell on the given device

        Args:
            nodeid (str): Unique id of node on which to open the shell

        Returns:
            :py:class:`~meshctrl.shell.Shell`: Newly created and initialized :py:class:`~meshctrl.shell.Shell` or cached :py:class:`~meshctrl.shell.Shell` if unique is False and a shell is currently active
         '''
        return shell.Shell(self, nodeid)


    def smart_shell(self, nodeid, regex):
        '''
        Get a smart terminal shell on the given device

        Args:
            nodeid (str): Unique id of node on which to open the shell
            regex (regex): Regex to watch for to signify that the shell is ready for new input.

        Returns:
            :py:class:`~meshctrl.shell.SmartShell`: Newly created and initialized :py:class:`~meshctrl.shell.SmartShell` or cached :py:class:`~meshctrl.shell.SmartShell` if unique is False and a smartshell with regex is currently active
         '''
        _shell = shell.Shell(self, nodeid)
        return shell.SmartShell(_shell, regex)


    async def wake_devices(self, nodeids, timeout=None):
        '''
        Wake up given devices
        TODO: This has no tests for it

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to wake
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(nodeids, str):
            nodeids = [nodeids]

        return await self._send_command({ "action": 'wakedevices', "nodeids": nodeids }, "wake_devices", timeout=timeout)

    async def reset_devices(self, nodeids, timeout=None):
        '''
        Reset given devices
        TODO: This has no tests for it

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to reset
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        if isinstance(nodeids, str):
            nodeids = [nodeids]

        return await self._send_command({ "action": 'poweraction', "nodeids": nodeids, "actiontype": 3 }, "reset_devices", timeout=timeout)

    async def sleep_devices(self, nodeids, timeout=None):
        '''
        Sleep given devices
        TODO: This has no tests for it

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to sleep
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        if isinstance(nodeids, str):
            nodeids = [nodeids]

        return await self._send_command({ "action": 'poweraction', "nodeids": nodeids, "actiontype": 4 }, "sleep_devices", timeout=timeout)

    async def power_off_devices(self, nodeids, timeout=None):
        ''' 
        Power off given devices
        TODO: This has no tests for it

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to power off
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        if isinstance(nodeids, str):
            nodeids = [nodeids]

        return await self._send_command({ "action": 'poweraction', "nodeids": nodeids, "actiontype": 2 }, "power_off_devices", timeout=timeout)

    async def list_device_shares(self, nodeid, timeout=None):
        '''
        List device shares of given node. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeid (str): Unique id of nodes of which to list shares
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            list[dict]: Array of dicts representing device shares

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        data = await self._send_command_no_response_id({ "action": 'deviceShares', "nodeid": nodeid }, timeout=timeout)
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])

        return data["deviceShares"]

    async def add_device_share(self, nodeid, name, type=constants.SharingType.desktop, consent=None, start=None, end=None, duration=60*60, timeout=None):
        '''
        Add device share to given node. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
        TODO: This has no tests for it

        Args:
            nodeid (str): Unique id of nodes of which to list shares
            name (str): Name of guest with which to share
            type (~meshctrl.constants.SharingType): Type of share thise should be
            consent (~meshctrl.constants.ConsentFlags): Consent flags for share. Defaults to "notify" for your given constants.SharingType
            start (int|datetime.datetime): When to start the share
            end (int|datetime.datetime): When to end the share. If None, use duration instead
            duration (int): Duration in seconds for share to exist
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            dict: Info about the newly created share

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            ValueError: If 'end' is some time before 'start'
            asyncio.TimeoutError: Command timed out
        '''
        if start is None:
             datetime.datetime.now()
        if consent is None:
            if type == constants.SharingType.desktop:
                consent = constants.ConsentFlags.desktopnotify
            else:
                consent = constants.ConsentFlags.terminalnotify

        start = int(start.timestamp())
        if end is None:
            end = start + duration
        else:
            end = int(start.timestamp())
        if end <= start:
            raise ValueError("End time must be ahead of start time")
        data = await self._send_command({ "action": 'createDeviceShareLink', "nodeid": nodeid, "guestname": name, "p": constants.SharingTypeEnum[type], "consent": consent, "start": start, "end": end }, "add_device_share", timeout=timeout)
        
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])

        del data["action"]
        del data["nodeid"]
        del data["tag"]
        del data["responseid"]
        return data

    async def remove_device_share(self, nodeid, shareid, timeout=None):
        '''
        Remove a device share
        TODO: This has no tests for it

        Args:
            nodeid (str): Unique node from which to remove the share
            shareid (str): Unique share id to be removed
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        data = await self._send_command({ "action": 'removeDeviceShare', "nodeid": nodeid, "publicid": shareid }, "remove_device_share", timeout=timeout)
        
        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])
        
        return True

    async def device_open_url(self, nodeid, url, timeout=None):
        '''
        Open url in browser on device. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
        TODO: This has no tests for it

        Args:
            nodeid (str): Unique node from which to remove the share
            url (str): url to open
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful, raise otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            Exception: `Failed to open url` if failure occurs
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        async def _():
            async for event in self.events({"type": "openUrl", "url": url}):
                if event["success"]:
                    return True
                else:
                    return False

        tasks = []
        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(asyncio.wait_for(_(), timeout=timeout)))
            tasks.append({ "action": 'msg', "type": 'openUrl', "nodeid": nodeid, "url": url }, "device_open_url", timeout=timeout)

        
        success = tasks[0].result()
        res = tasks[1].result()

        if res.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])

        if not success:
            raise exceptions.ServerError("Failed to open url")

        return True

    async def device_message(self, nodeid, message, title="MeshCentral", timeout=None):
        '''
        Display a message on remote device.
        TODO: This has no tests for it

        Args:
            nodeid (str): Unique node from which to remove the share
            message (str): message to display
            title (str): message title
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
           bool: True if successful, raile otherwise

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        data = await self._send_command({ "action": 'msg', "type": 'messagebox', "nodeid": nodeid, "title": title, "msg": message }, "device_message", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])

        return True

    async def device_toast(self, nodeids, message, title="MeshCentral", timeout=None):
        '''
        Popup a toast a message on remote device.
        TODO: This has no tests for it

        Args:
            nodeids (str|list[str]): Unique node from which to remove the share
            message (str): message to display
            title (str): message title
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
            @todo This function returns True even if it fails, because the server tells us it succeeds before it actually knows, then later tells us it failed, but it's hard to find that because it looks exactly like a success.
         '''
        if isinstance(nodeids, str):
            nodeids = [nodeids]

        data = self._send_command({ "action": 'toast', "nodeids": nodeids, "title": "MeshCentral", "msg": message }, "device_toast", timeout=timeout)

        if data.get("result", "ok").lower() != "ok":
            raise exceptions.ServerError(data["result"])

        return True

    @util._check_socket
    async def interuser(self, data, session=None, user=None):
        '''
        Fire off an interuser message. This is a fire and forget api, we have no way of checking if the user got the message.
        User will recieve an :py:class:`~meshctrl.types.InteruserMessage` if they are allowed to receive interuser messages from you.

        Args:
            data (serializable): Any sort of serializable data you want to send to the user
            session (str): Direct session to send to. Use this after you have made connection with a specific user session.
            user (str): Send message to all sessions of a particular user. One of these must be set.

        Raises:    
            ValueError: Value error if neither user nor session are given.
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
         '''
        if session is None and user is None:
            raise ValueError("No user or session given")
        await self._message_queue.put(json.dumps({"action": "interuser", "data": data, "sessionid": session, "userid": user}))

    async def upload(self, node, source, target, unique_file_tunnel=False, timeout=None):
        '''
        Upload a stream to a device.

        Args:
            node (~meshctrl.device.Device|str): Device or id of device to which to upload the file. If it is a device, it must have a ~meshctrl.mesh.Mesh device associated with it (the default). If it is a string, the device will be fetched prior to tunnel creation.
            source (io.IOBase): An IO instance from which to read the data. Must be open for reading.
            target (str): Path which to upload stream to on remote device
            unique_file_tunnel (bool): True: Create a unique :py:class:`~meshctrl.files.Files` for this call, which will be cleaned up on return, else use cached or cache :py:class:`~meshctrl.files.Files`
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.FileTransferError`: File transfer failed. Info available on the `stats` property
            :py:class:`~meshctrl.exceptions.FileTransferCancelled`: File transfer cancelled. Info available on the `stats` property

        Returns:
            dict: {result: bool whether upload succeeded, size: number of bytes uploaded}
        '''
        if not isinstance(node, device.Device):
            node = await self.device_info(node)
        if unique_file_tunnel:
            async with self.file_explorer(node) as files:
                return await files.upload(source, target, timeout=timeout)
        else:
            files = await self._cached_file_explorer(node, node.nodeid)
            return await files.upload(source, target, timeout=timeout)


    async def upload_file(self, node, filepath, target, unique_file_tunnel=False, timeout=None):
        '''
        Friendly wrapper around :py:class:`~meshctrl.session.Session.upload` to upload from a filepath. Creates a ReadableStream and calls upload.

        Args:
            node (~meshctrl.device.Device|str): Device or id of device to which to upload the file. If it is a device, it must have a ~meshctrl.mesh.Mesh device associated with it (the default). If it is a string, the device will be fetched prior to tunnel creation.
            filepath (str): Path from which to read the data
            target (str): Path which to upload file to on remote device
            unique_file_tunnel (bool): True: Create a unique :py:class:`~meshctrl.files.Files` for this call, which will be cleaned up on return, else use cached or cache :py:class:`~meshctrl.files.Files`
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.FileTransferError`: File transfer failed. Info available on the `stats` property
            :py:class:`~meshctrl.exceptions.FileTransferCancelled`: File transfer cancelled. Info available on the `stats` property

        Returns:
            dict: {result: bool whether upload succeeded, size: number of bytes uploaded}
         '''
        with open(filepath, "rb") as f:
            return await self.upload(node, f, target, unique_file_tunnel, timeout=timeout)

    async def download(self, node, source, target=None, skip_http_attempt=False, skip_ws_attempt=False, unique_file_tunnel=False, timeout=None):
        '''
        Download a file from a device into a writable stream. This creates an :py:class:`~meshctrl.files.Files` and destroys it every call. If you need to upload multiple files, use :py:class:`~meshctrl.session.Session.file_explorer` instead.

        Args:
            node (~meshctrl.device.Device|str): Device or id of device from which to download the file. If it is a device, it must have a ~meshctrl.mesh.Mesh device associated with it (the default). If it is a string, the device will be fetched prior to tunnel creation.
            source (str): Path from which to download from device
            target (io.IOBase): Stream to which to write data. If None, create new BytesIO which is both readable and writable.
            skip_http_attempt (bool): Meshcentral has a way to download files through http(s) instead of through the websocket. This method tends to be much faster than using the websocket, so we try it first. Setting this to True will skip that attempt and just use the established websocket connection.
            skip_ws_attempt (bool): Like skip_http_attempt, except just throw an error if the http attempt fails instead of trying with the websocket
            unique_file_tunnel (bool): True: Create a unique :py:class:`~meshctrl.files.Files` for this call, which will be cleaned up on return, else use cached or cache :py:class:`~meshctrl.files.Files`
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.FileTransferError`: File transfer failed. Info available on the `stats` property
            :py:class:`~meshctrl.exceptions.FileTransferCancelled`: File transfer cancelled. Info available on the `stats` property

        Returns:
            io.IOBase: The stream which has been downloaded into. Cursor will be at the beginning of where the file is downloaded.
        '''
        if not isinstance(node, device.Device):
            node = await self.device_info(node)
        if target is None:
            target = io.BytesIO()
        start = target.tell()
        if unique_file_tunnel:
            async with self.file_explorer(node) as files:
                await files.download(source, target, skip_http_attempt=skip_http_attempt, skip_ws_attempt=skip_ws_attempt, timeout=timeout)
                target.seek(start)
                return target
        else:
            files = await self._cached_file_explorer(node, node.nodeid)
            await files.download(source, target, skip_http_attempt=skip_http_attempt, skip_ws_attempt=skip_ws_attempt, timeout=timeout)
            target.seek(start)
            return target

    async def download_file(self, node, source, filepath, skip_http_attempt=False, skip_ws_attempt=False, unique_file_tunnel=False, timeout=None):
        '''
        Friendly wrapper around :py:class:`~meshctrl.session.Session.download` to download to a filepath. Creates a WritableStream and calls download.

        Args:
            node (~meshctrl.device.Device|str): Device or id of device from which to download the file. If it is a device, it must have a ~meshctrl.mesh.Mesh device associated with it (the default). If it is a string, the device will be fetched prior to tunnel creation.
            source (str): Path from which to download from device
            filepath (str): Path to which to download data
            skip_http_attempt (bool): Meshcentral has a way to download files through http(s) instead of through the websocket. This method tends to be much faster than using the websocket, so we try it first. Setting this to True will skip that attempt and just use the established websocket connection.
            skip_ws_attempt (bool): Like skip_http_attempt, except just throw an error if the http attempt fails instead of trying with the websocket
            unique_file_tunnel (bool): True: Create a unique :py:class:`~meshctrl.files.Files` for this call, which will be cleaned up on return, else use cached or cache :py:class:`~meshctrl.files.Files`
            timeout (int): duration in seconds to wait for a response before throwing an error

        Raises:
            :py:class:`~meshctrl.exceptions.FileTransferError`: File transfer failed. Info available on the `stats` property
            :py:class:`~meshctrl.exceptions.FileTransferCancelled`: File transfer cancelled. Info available on the `stats` property

        Returns:
            None
         '''
        with open(filepath, "wb") as f:
            await self.download(node, source, f, skip_http_attempt=skip_http_attempt, skip_ws_attempt=skip_ws_attempt, unique_file_tunnel=unique_file_tunnel, timeout=timeout)

    async def _cached_file_explorer(self, node, _id):
        if (_id not in self._file_tunnels or not self._file_tunnels[_id].alive):
            self._file_tunnels[_id] = await self.file_explorer(node).__aenter__()
        await self._file_tunnels[_id].initialized.wait()
        return self._file_tunnels[_id]

    def file_explorer(self, node):
        '''
        Create, initialize, and return an :py:class:`~meshctrl.files.Files` object for the given node

        Args:
            node (~meshctrl.device.Device|str): Device or id of device on which to open file explorer. If it is a device, it must have a ~meshctrl.mesh.Mesh device associated with it (the default). If it is a string, the device will be fetched prior to tunnel creation.

        Returns:
            :py:class:`~meshctrl.files.Files`: A newly initialized file explorer.
        '''
        return _FileExplorerWrapper(self, node)


# This is a little yucky, but I can't get a good API otherwise. Since Tunnel objects are only useable as context managers anyway, this should be fine.
class _FileExplorerWrapper:
    def __init__(self, session, node):
        self.session = session
        self.node = node
        self._files = None

    async def __aenter__(self):
        if not isinstance(self.node, device.Device):
            self.node = await self.session.device_info(self.node)
        self._files = files.Files(self.session, self.node)
        return await self._files.__aenter__()

    async def __aexit__(self, exc_t, exc_v, exc_tb):
        return await self._files.__aexit__(exc_t, exc_v, exc_tb)
