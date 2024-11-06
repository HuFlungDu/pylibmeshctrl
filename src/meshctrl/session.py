import websockets
import websockets.datastructures
import websockets.asyncio
import websockets.asyncio.client
import asyncio
import base64
import json
from . import constants
from . import exceptions
from . import util

def _check_socket(f):
    async def wrapper(self, *args, **kwargs):
        await self.initialized.wait()
        if not self.alive:
            raise self._main_loop_error
        return await f(self, *args, **kwargs)
    return wrapper

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

    Returns:
        :py:class:`Session`: Session connected to url

    Attributes:
        url (str): url to which the session is connected
        initialized (asyncio.Event): Event marking if the Session initialization has finished. Wait on this to wait for a connection.
        alive (bool): Whether the session connection is currently alive
    '''

    def __init__(self, url, user=None, domain=None, password=None, loginkey=None, proxy=None, token=None, ignore_ssl=False, auto_reconnect=False):
        if len(url) < 5 or ((not url.startswith('wss://')) and (not url.startsWith('ws://'))):
            raise ValueError("Invalid URL")

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
        self._password = password
        self._token = token
        self._loginkey = loginkey
        self._socket_open = asyncio.Event()
        self._inflight = set()
        self._file_tunnels = {}
        self._shell_tunnels = {}
        self._smart_shell_tunnels = {}
        self._ignoreSSL = ignoreSSL

        self._eventer = util.Eventer()

        self.initialized = asyncio.Event()
        self._initialization_err = None

        self._main_loop_task = asyncio.create_task(self._main_loop())
        self._main_loop_error = None

        self._server_info = {}
        self._user_info = {}
        self._command_id = 0
        self.alive = False

        self._message_queue = asyncio.Queue()
        self._send_task = None
        self._listen_task = None

    async def _main_loop(self):
        options = {}
        if self._ignoreSSL:
            options = { ssl: False }

        # Setup the HTTP proxy if needed
        # if (self._proxy != None):
        #     options.agent = new https_proxy_agent(urllib.parse(this._proxy))

        headers = websockets.datastructures.Headers()

        if (self._password):
            token = self._token if self._token else b""
            headers['x-meshauth'] = (base64.b64encode(self._user.encode()) + b',' + base64.b64encode(self._password.encode()) + token).decode()

        options["additional_headers"] = headers
        async for websocket in websockets.asyncio.client.connect(self.url, **options):
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
            except* Exception as e:
                self.initialized.set()
                self.alive = False
                self._socket_open.clear()
                self._main_loop_error = e

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
            data = json.loads(message)
            action = data.get("action", None)
            if action == "close":
                if data.get("cause", None) == "noauth":
                    raise exceptions.ServerError("Invalid Auth")
            if action == "userinfo":
                self._user_info = data["userinfo"]
                self.initialized.set()

            if action == "serverinfo":
                self._currentDomain = data["serverinfo"]["domain"]
                self._server_info = data["serverinfo"]

            if action in ("event", "msg", "interuser"):
                self._eventer.emit("server_event", data)

            id = data.get("responseid", data.get("tag", None))
            if id:
                self._eventer.emit(id, data)
            else:
                # Some events don't user their response id, they just have the action. This should be fixed eventually.
                # Broken commands include:
                #      meshes
                #      nodes
                #      getnetworkinfo
                #      lastconnect
                #      getsysinfo
                # console.log(`emitting ${data.action}`)
                self._eventer.emit(action, data)

    def _get_command_id(self):
        self._command_id = (self._command_id+1)%(2**32-1)
        return self._command_id

    async def close(self):
        # Dunno yet
        self._main_loop_task.cancel()
        try:
            await self._main_loop_task
        except asyncio.CancelledError:
            pass


    async def __aenter__(self):
        await self.initialized.wait()
        return self

    async def __aexit__(self, exc_t, exc_v, exc_tb):
        await self.close()

    @_check_socket
    async def _send_command(self, data, name, timeout=None):
        id = f"meshctrl_{name}_{self._get_command_id()}"
        # This fixes a very theoretical bug with hash colisions in the case of an infinite int of requests. Now the bug will only happen if there are currently 2**32-1 of the same type of request going out at the same time
        while id in self._inflight:
            id = f"meshctrl_{name}_{self._get_command_id()}"

        self._inflight.add(id)
        responded = asyncio.Event()
        response = None
        def _(data):
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

    @_check_socket
    async def _send_command_no_response_id(self, data, timeout=None):
        responded = asyncio.Event()
        response = None
        def _(data):
            nonlocal response
            response = data
            responded.set()
        self._eventer.once(data["action"], _)
        await self._message_queue.put(data | {"tag": id, "responseid": id})
        await asyncio.wait_for(responded.wait(), timeout=timeout)
        if isinstance(response, Exception):
            raise response
        return response

    async def list_device_groups(self, timeout=None):
        '''
        Get device groups. Only returns meshes to which the logged in user has access

        Args:
            timeout (int): Duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict]: List of meshes

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error from server
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        data = await self._send_command({"action": "meshes"}, "list_device_groups", timeout)
        return data["meshes"]


    async def send_invite_email(self, group, email, name=None, message=None, meshid=None, timeout=None):
        '''
        Send an invite email for a group or mesh

        Args:
            group (str): Name of mesh to which to invite email
            email (str): Email of user to invite
            name (str): User's name. For display purposes.
            message (str): Message to send to user in invite email
            meshid (str): ID of mesh which to invite user. Overrides "group"
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, False otherwise

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def generate_invite_link(self, group, hours, flags=None, meshid=None, timeout=None):
        '''
        Generate an invite link for a group or mesh

        Args:
            group (str): Name of group to add
            hours (int): Hours until link expires
            flags (~meshctrl.constants.MeshRights): Bitwise flags for constants.MeshRights
            meshid (str): ID of mesh which to invite user. Overrides "group"
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: Invite link information

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def list_users(self, timeout=None):
        '''
        List users on server. Admin Only.

        Args:
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict]: List of users

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

    async def list_user_sessions(self, timeout=None):
        '''
        Get list of connected users. Admin Only.

        Args:
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict] List of user sessions

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

    async def list_user_groups(self, timeout=None):
        '''
        Get user groups. Admin will get all user groups, otherwise get limited user groups

        Args:
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict]: List of groups

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

    
    async def list_devices(self, details=False, group=None, meshid=None, timeout=None):
        '''
        Get devices to which the user has access.

        Args:
            details (bool): Get device details
            group (str): Get devices from specific group by name. Overrides meshid
            meshid (str): Get devices from specific group by id
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict]: List of nodes

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    

    def on_close(self, f):
        '''
        Listen for the socket to close

        Args:
            f (function(data: dict)): Function to call when the socket closes
         '''
        raise NotImplementedError()

    def listen_to_events(self, f, filter=None):
        '''
        Listen to events from the server

        Args:
            f (function(data: dict)): Function to call when an event occurs
            filter (dict): dict to filter events with. Only trigger for events that deep-match this dict. Use sets for "array.contains" and arrays for equality of lists.

        Returns:
            function: - Function used for listening. Use this to stop listening to events if you want that.
         '''
        raise NotImplementedError()
    
    def stop_listening_to_events(self, f):
        '''
        Stop listening to server events

        Args:
            @param {function} Callback to stop listening with.
        '''
        raise NotImplementedError()

    async def list_events(self, userid=None, nodeid=None, limit=None, timeout=None):
        '''
        List events visible to the currect user

        Args:
            userid (str): Filter by user. Overrides nodeid.
            nodeid (str): Filter by node
            limit (int): Limit to the N most recent events
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict]: List of events

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def list_login_tokens(self, timeout=None):
        '''
        List login tokens for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict]: List of tokens

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def add_login_token(self, name, expire=None, timeout=None):
        '''
        Create login token for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            name (str): Name of token
            expire (int): Minutes until expiration. 0 or None for no expiration.
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: Created token

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def remove_login_token(self, names, timeout=None):
        '''
        Remove login token for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            name (str): Name of token or token username
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict]: List of remaining tokens

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def add_user(self, name, password, randompass=False, domain=None, email=None, emailverified=False, resetpass=False, realname=None, phone=None, rights=None, timeout=None):
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
            phone (str): User's phone int
            rights (~meshctrl.constants.UserRights): Bitwise mask of user's rights on the server
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

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
            phone (str): User's phone int
            rights (~meshctrl.constants.UserRights): Bitwise mask of user's rights on the server
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def remove_user(self, userid, timeout=None):
        '''
        Remove an existing user

        Args:
            userid (str): Unique userid
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def add_user_group(self, name, description=None, timeout=None):
        '''
        Create a new user group

        Args:
            name (str): Name of usergroup
            description (str): Description of user group
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: New user group

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def remove_user_group(self, groupid, timeout=None):
        '''
        Remove an existing user group

        Args:
            userid (str): Unique userid
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def add_users_to_user_group(self, userids, groupid, timeout=None):
        '''
        Add user(s) to an existing user group. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            ids (str|list[str]): Unique user id(s)
            groupid (str): Group to add the given user to
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[str]: List of users that were successfully added

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def remove_user_from_user_group(self, userid, groupid, timeout=None):
        '''
        Remove user from an existing user group

        Args:
            id (str): Unique user id
            groupid (str): Group to remove the given user from
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def add_users_to_device(self, userids, nodeid, rights=None, timeout=None):
        '''
        Add a user to an existing node

        Args:
            userids (str|list[str]): Unique user id(s)
            nodeid (str): Node to add the given user to
            rights (~meshctrl.constants.MeshRights): Bitwise mask for the rights on the given mesh
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def remove_users_from_device(self, nodeid, userids, timeout=None):
        '''
        Remove users from an existing node

        Args:
            nodeid (str): Node to remove the given users from
            userids (str|list[str]): Unique user id(s)
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def add_device_group(self, name, description="", amtonly=False, features=0, consent=0, timeout=None):
        '''
        Create a new device group

        Args:
            name (str): Name of device group
            description (str): Description of device group
            amtonly (bool): 
            features (~meshctrl.constants.MeshFeatures): Bitwise features to enable on the group
            consent (~meshctrl.constants.ConsentFlags): Bitwise consent flags to use for the group
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: New device group

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def remove_device_group(self, meshid, isname=False, timeout=None):
        '''
        Remove an existing device group

        Args:
            meshid (str): Unique id of device group
            isname (bool): treat "meshid" as a name instead of an id
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def edit_device_group(self, meshid, isname=False, name=None, description=None, flags=None, consent=None, invite_codes=None, backgroundonly=False, interactiveonly=False, timeout=None):
        '''
        Edit an existing device group

        Args:
            meshid (str): Unique id of device group
            isname (bool): treat "meshid" as a name instead of an id
            name (str): New name for group
            description (str): New description
            flags (~meshctrl.constants.MeshFeatures): Features to enable on the group
            consent (~meshctrl.constants.ConsentFlags): Which consent flags to use for the group
            invite_codes (list[str]): Create new invite codes
            backgroundonly (bool): Flag for invite codes
            interactiveonly (bool): Flag for invite codes
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def move_to_device_group(self, nodeids, meshid, isname=False, timeout=None):
        '''
        Move a device from one group to another

        Args:
            nodeids (str|list[str]): Unique node id(s)
            meshid (str): Unique mesh id
            isname (bool): treat "meshid" as a name instead of an id
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, otherwise False

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def add_users_to_device_group(self, userids, meshid, isname=False, rights=0, timeout=None):
        '''
        Add a user to an existing mesh

        Args:
            userids (str|list[str]): Unique user id(s)
            meshid (str): Mesh to add the given user to
            isname (bool): Read meshid as a name rather than an id
            rights (~meshctrl.constants.MeshRights): Bitwise mask for the rights on the given mesh
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: Object showing which were added correctly and which were not, along with their result messages

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def remove_users_from_device_group(self, userids, meshid, isname=False, timeout=None):
        '''
        Remove users from an existing mesh

        Args:
            userids (str|list[str]): Unique user id(s)
            meshid (str): Mesh to add the given user to
            isname (bool): Read meshid as a name rather than an id
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: Object showing which were removed correctly and which were not

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def broadcast(self, message, userid=None, timeout=None):
        '''
        Broadcast a message to all users or a single user

        Args:
            message (str): Message to broadcast
            userid (str): Optional user to which to send the message
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def device_info(self, nodeid, timeout=None):
        '''
        Get all info for a given device. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeid (str): Unique id of desired node
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: Object containing all meaningful device info

        Raises:    
            ValueError: `Invalid device id` if device is not found
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

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
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def run_command(self, nodeids, command, powershell=False, runasuser=False, runasuseronly=False, timeout=None):
        '''
        Run a command on any int of nodes. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeids (str|list[str]): Unique ids of nodes on which to run the command
            command (str): Command to run
            powershell (bool): Use powershell to run command. Only available on Windows.
            runasuser (bool): Attempt to run as a user instead of the root permissions given to the agent. Fall back to root if we cannot.
            runasuseronly (bool): Error if we cannot run the command as the logged in user.
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: Object containing mapped output of the commands by device

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def shell(self, nodeid, unique=False):
        '''
        Get a terminal shell on the given device

        Args:
            nodeid (str): Unique id of node on which to open the shell
            unique (bool): True: Create a unique :py:class:`~meshctrl.shell.Shell`. Caller is responsible for cleanup. False: Use a cached :py:class:`~meshctrl.shell.Shell` if available, otherwise create and cache.

        Returns:
            :py:class:`~meshctrl.shell.Shell`: Newly created and initialized :py:class:`~meshctrl.shell.Shell` or cached :py:class:`~meshctrl.shell.Shell` if unique is False and a shell is currently active
         '''
        raise NotImplementedError()

    async def smart_shell(self, nodeid, regex, unique=False):
        '''
        Get a smart terminal shell on the given device

        Args:
            nodeid (str): Unique id of node on which to open the shell
            regex (regex): Regex to watch for to signify that the shell is ready for new input.
            unique (bool): true: Create a unique :py:class:`~meshctrl.shell.SmartShell`. Caller is responsible for cleanup. False: Use a cached :py:class:`~meshctrl.shell.SmartShell` if available, otherwise create and cache.
        Returns:
            :py:class:`~meshctrl.shell.SmartShell`: Newly created and initialized :py:class:`~meshctrl.shell.SmartShell` or cached :py:class:`~meshctrl.shell.SmartShell` if unique is False and a smartshell with regex is currently active
         '''
        raise NotImplementedError()

    async def wake_devices(self, nodeids, timeout=None):
        '''
        Wake up given devices

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to wake
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def reset_devices(self, nodeids, timeout=None):
        '''
        Reset given devices

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to reset
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def sleep_devices(self, nodeids, timeout=None):
        '''
        Sleep given devices

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to sleep
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

    async def power_off_devices(self, nodeids, timeout=None):
        ''' Power off given devices

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to power off
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

    async def list_device_shares(self, nodeid, timeout=None):
        '''
        List device shares of given node. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeid (str): Unique id of nodes of which to list shares
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            list[dict]: Array of dicts representing device shares

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

    async def add_device_share(self, nodeid, name, type=constants.SharingType.desktop, consent=None, start=None, end=None, duration=60*60, timeout=None):
        '''
        Add device share to given node. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeid (str): Unique id of nodes of which to list shares
            name (str): Name of guest with which to share
            type (~meshctrl.constants.SharingType): Type of share thise should be
            consent (~meshctrl.constants.ConsentFlags): Consent flags for share. Defaults to "notify" for your given constants.SharingType
            start (int|datetime.datetime): When to start the share
            end (int|datetime.datetime): When to end the share. If None, use duration instead
            duration (int): Duration in seconds for share to exist
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict: Info about the newly created share

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

    async def remove_device_share(self, nodeid, shareid, timeout=None):
        '''
        Remove a device share

        Args:
            nodeid (str): Unique node from which to remove the share
            shareid (str): Unique share id to be removed
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: true if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        raise NotImplementedError()

    async def device_open_url(self, nodeid, url, timeout=None):
        '''
        Open url in browser on device. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            nodeid (str): Unique node from which to remove the share
            url (str): url to open
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: true if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            Exception: `Failed to open url` if failure occurs
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def device_message(self, nodeid, message, title="MeshCentral", timeout=None):
        '''
        Display a message on remote device.

        Args:
            nodeid (str): Unique node from which to remove the share
            message (str): message to display
            title (str): message title
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
           bool: true if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        raise NotImplementedError()

    async def device_toast(self, nodeids, message, title="MeshCentral", timeout=None):
        '''
        Popup a toast a message on remote device.

        Args:
            nodeids (str|list[str]): Unique node from which to remove the share
            message (str): message to display
            title (str): message title
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: true if successful

        Raises:    
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
            @todo This function returns true even if it fails, because the server tells us it succeeds before it actually knows, then later tells us it failed, but it's hard to find that because it looks exactly like a success.
         '''
        raise NotImplementedError()

    def interuser(self, data, session=None, user=None):
        '''
        Fire off an interuser message. This is a fire and forget api, we have no way of checking if the user got the message.

        Args:
            data (serializable): Any sort of serializable data you want to send to the user
            session (str): Direct session to send to. Use this after you have made connection with a specific user session.
            user (str): Send message to all sessions of a particular user. One of these must be set.

        Raises:    
            ValueError: Value error if neither user nor session are given.
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
         '''
        raise NotImplementedError()

    async def upload(self, nodeid, source, target, unique_file_tunnel=False):
        '''
        Upload a stream to a device. This creates an _File and destroys it every call. If you need to upload multiple files, use {@link Session#file_explorer} instead.

        Args:
            nodeid (str): Unique id to upload stream to
            source (ReadableStream): ReadableStream from which to read data
            target (str): Path which to upload stream to on remote device
            unique_file_tunnel (bool): True: Create a unique :py:class:`~meshctrl.files.Files` for this call, which will be cleaned up on return, else use cached or cache :py:class:`~meshctrl.files.Files`

        Returns:
            Promise<Object>: {result: bool whether upload succeeded, size: number of bytes uploaded}
        '''
        raise NotImplementedError()

    async def upload_file(self, nodeid, filepath, target, unique_file_tunnel=False):
        '''
        Friendly wrapper around :py:class:`~meshctrl.session.Session.upload` to upload from a filepath. Creates a ReadableStream and calls upload.

        Args:
            nodeid (str): Unique id to upload file to
            filepath (str): Path from which to read the data
            target (str): Path which to upload file to on remote device
            unique_file_tunnel (bool): True: Create a unique :py:class:`~meshctrl.files.Files` for this call, which will be cleaned up on return, else use cached or cache :py:class:`~meshctrl.files.Files`

        Returns:
            dict: {result: bool whether upload succeeded, size: number of bytes uploaded}
         '''
        raise NotImplementedError()

    async def download(self, nodeid, source, target=None, unique_file_tunnel=False):
        '''
        Download a file from a device into a writable stream. This creates an :py:class:`~meshctrl.files.Files` and destroys it every call. If you need to upload multiple files, use :py:class:`~meshctrl.session.Session.file_explorer` instead.

        Args:
            nodeid (str): Unique id to download file from
            source (str): Path from which to download from device
            target (WritableStream): Stream to which to write data. If None, create new PassThrough stream which is both readable and writable.
            unique_file_tunnel (bool): True: Create a unique :py:class:`~meshctrl.files.Files` for this call, which will be cleaned up on return, else use cached or cache :py:class:`~meshctrl.files.Files`

        Returns:
            WritableStream: The stream which has been downloaded into

        Raises:    
            Exception: String showing the intermediate outcome and how many bytes were downloaded
         '''
        raise NotImplementedError()

    async def download_file(self, nodeid, source, filepath, unique_file_tunnel=False):
        '''
        Friendly wrapper around :py:class:`~meshctrl.session.Session.download` to download to a filepath. Creates a WritableStream and calls download.

        Args:
            nodeid (str): Unique id to download file from
            source (str): Path from which to download from device
            filepath (str): Path to which to download data
            unique_file_tunnel (bool): True: Create a unique :py:class:`~meshctrl.files.Files` for this call, which will be cleaned up on return, else use cached or cache :py:class:`~meshctrl.files.Files`

        Returns:
            WritableStream: The stream which has been downloaded into
         '''
        raise NotImplementedError()

    async def file_explorer(self, nodeid, unique=False):
        '''
        Create, initialize, and return an :py:class:`~meshctrl.files.Files` object for the given node

        Args:
            nodeid (str): Unique id on which to open file explorer
            unique (bool): True: Create a unique :py:class:`~meshctrl.files.Files`. Caller is responsible for cleanup. False: Use a cached :py:class:`~meshctrl.files.Files` if available, otherwise create and cache.

        Returns:
            :py:class:`~meshctrl.files.Files`: A newly initialized file explorer.
         '''
        raise NotImplementedError()