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
    def __init__(self, url, user=None, domain=None, password=None, loginkey=None, proxy=None, token=None, ignoreSSL=False, auto_reconnect=False):
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
            url += '?auth=' + util.encode_cookie({ userid: 'user/' + domainid + '/' + username, domainid: domainid }, ckey)

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
        # This fixes a very theoretical bug with hash colisions in the case of an infinite number of requests. Now the bug will only happen if there are currently 2**32-1 of the same type of request going out at the same time
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


    '''*
     * Get device groups. Only returns meshes to which the logged in user has access
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<Object[]>} List of meshes
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def list_device_groups(self, timeout=None):
        data = await self._send_command({"action": "meshes"}, "list_device_groups", timeout)
        return data["meshes"]

    '''* 
     * Send an invite email for a group or mesh
     * @param {string} group - Name of mesh to which to invite email
     * @param {string} email - Email of user to invite
     * @param {Object} [options={}]
     * @param {string} [options.name=None] - User's name. For display purposes.
     * @param {string} [options.message=None] - Message to send to user in invite email
     * @param {string} [options.meshid=None] - ID of mesh which to invite user. Overrides "group"
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def send_invite_email(group, email, name=None, message=None, meshid=None, timeout=None):
        raise NotImplementedError()

    '''* 
     * Generate an invite link for a group or mesh
     * @param {string} group - Name of group to add
     * @param {number} hours - Hours until link expires
     * @param {Object} [options={}]
     * @param {constants.MeshRights} [options.flags=None] - Bitwise flags for constants.MeshRights
     * @param {string} [options.meshid=None] - ID of mesh which to invite user. Overrides "group"
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Object>} Invite link information
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def generate_invite_link(group, hours, flags=None, meshid=None, timeout=None):
        raise NotImplementedError()

    '''*
     * List users on server. Admin Only.
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<Object[]>} List of users
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def list_users(timeout=None):
        raise NotImplementedError()

    '''*
     * Get list of connected users. Admin Only.
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<Object[]>} List of user sessions
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def list_user_sessions(timeout=None):
        raise NotImplementedError()

    '''*
     * Get user groups. Admin will get all user groups, otherwise get limited user groups
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<Object[]|None>} List of groups, or None if no groups are found
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def list_user_groups(timeout=None):
        raise NotImplementedError()

    '''*
     * Get devices to which the user has access.
     * @param {Object} [options={}]
     * @param {boolean} [options.details=False] - Get device details
     * @param {string} [options.group=None] - Get devices from specific group by name. Overrides meshid
     * @param {string} [options.meshid=None] - Get devices from specific group by id
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<Object[]>} List of nodes
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def list_devices(details=False, group=None, meshid=None, timeout=None):
        raise NotImplementedError()

    '''*
     * @callback Session~CloseCallback
     * @param {SocketError} err - Error explaining the closure to the best of our ability
     '''

    '''*
     * Listen for the socket to close
     * @param {Session~CloseCallback} f - Function to call when the socket closes
     '''

    def on_close(f):
        raise NotImplementedError()

    '''*
     * @callback Session~EventCallback
     * @param {Object} data - Raw event data from the server
     '''

    '''*
     * Listen to events from the server
     * @param {Session~EventCallback} f - Function to call when an event occurs
     * @param {Object} [filter=None] - Object to filter events with. Only trigger for events that deep-match this object. Use sets for "array.contains" and arrays for equality of lists.
     * @return {function} - Function used for listening. Use this to stop listening to events if you want that.
     '''
    def listen_to_events(f, filter=None):
        raise NotImplementedError()

    '''*
     * Stop listening to server events
     * @param {function} Callback to stop listening with.
     '''
    def stop_listening_to_events(f):
        raise NotImplementedError()

    '''* 
     * List events visible to the currect user
     * @param {Object} [options={}]
     * @param {string} [options.userid=None] - Filter by user. Overrides nodeid.
     * @param {string} [options.nodeid=None] - Filter by node
     * @param {number} [options.limit=None] - Limit to the N most recent events
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Object[]>} List of events
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def list_events(userid=None, nodeid=None, limit=None, timeout=None):
        raise NotImplementedError()

    '''* 
     * List login tokens for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Object[]>} List of tokens
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def list_login_tokens(timeout=None):
        raise NotImplementedError()

    '''* 
     * Create login token for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {string} name - Name of token
     * @param {number} [expire=None] - Minutes until expiration. 0 or None for no expiration.
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Object>} Created token
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def add_login_token(name, expire=None, timeout=None):
        raise NotImplementedError()

    '''* 
     * Remove login token for current user. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {string} name - Name of token or token username
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Object[]>} List of remaining tokens
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def remove_login_token(names, timeout=None):
        raise NotImplementedError()

    '''* 
     * Add a new user
     * @param {string} name - username
     * @param {string} password - user's starting password
     * @param {Object} [options={}]
     * @param {boolean} [options.randompass=False] - Generate a random password for the user. Overrides password
     * @param {string} [options.domain=None] - Domain to which to add the user
     * @param {string} [options.email=None] - User's email address
     * @param {boolean} [options.emailverified=False] - Pre-verify the user's email address
     * @param {boolean} [options.resetpass=False] - Force the user to reset their password on first login
     * @param {string} [options.realname=None] - User's real name
     * @param {string} [options.phone=None] - User's phone number
     * @param {constants.UserRights} [options.rights=None] - Bitwise mask of user's rights on the server
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def add_user(name, password, randompass=False, domain=None, email=None, emailverified=False, resetpass=False, realname=None, phone=None, rights=None, timeout=None):
        raise NotImplementedError()

    '''* 
     * Edit an existing user
     * @param {string} userid - Unique userid
     * @param {Object} [options={}]
     * @param {string} [options.domain=None] - Domain to which to add the user
     * @param {string} [options.email=None] - User's email address
     * @param {boolean} [options.emailverified=False] - Verify or unverify the user's email address
     * @param {boolean} [options.resetpass=False] - Force the user to reset their password on next login
     * @param {string} [options.realname=None] - User's real name
     * @param {string} [options.phone=None] - User's phone number
     * @param {constants.UserRights} [options.rights=None] - Bitwise mask of user's rights on the server
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def edit_user(userid, domain=None, email=None, emailverified=False, resetpass=False, realname=None, phone=None, rights=None, timeout=None):
        raise NotImplementedError()

    '''* 
     * Remove an existing user
     * @param {string} userid - Unique userid
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def remove_user(userid, timeout=None):
        raise NotImplementedError()

    '''* 
     * Create a new user group
     * @param {string} name - Name of usergroup
     * @param {string} [description=None] - Description of user group
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Object>} New user group
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def add_user_group(name, description=None, timeout=None):
        raise NotImplementedError()

    '''* 
     * Remove an existing user group
     * @param {string} userid - Unique userid
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def remove_user_group(groupid, timeout=None):
        raise NotImplementedError()

    '''* 
     * Add user(s) to an existing user group. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {string|array} ids - Unique user id(s)
     * @param {string} groupid - Group to add the given user to
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<string[]>} List of users that were successfully added
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def add_users_to_user_group(userids, groupid, timeout=None):
        raise NotImplementedError()

    '''* 
     * Remove user from an existing user group
     * @param {string} id - Unique user id
     * @param {string} groupid - Group to remove the given user from
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def remove_user_from_user_group(userid, groupid, timeout=None):
        raise NotImplementedError()

    '''* 
     * Add a user to an existing node
     * @param {string|array} userids - Unique user id(s)
     * @param {string} nodeid - Node to add the given user to
     * @param {constants.MeshRights} [rights=None] - Bitwise mask for the rights on the given mesh
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def add_users_to_device(userids, nodeid, rights=None, timeout=None):
        raise NotImplementedError()

    '''* 
     * Remove users from an existing node
     * @param {string} nodeid - Node to remove the given users from
     * @param {string|array} userids - Unique user id(s)
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def remove_users_from_device(nodeid, userids, timeout=None):
        raise NotImplementedError()

    '''* 
     * Create a new device group
     * @param {string} name - Name of device group
     * @param {Object} [options={}]
     * @param {string} [options.description=""] - Description of device group
     * @param {boolean} [options.amtonly=False] - 
     * @param {constants.MeshFeatures} [options.features=0] - Bitwise features to enable on the group
     * @param {constants.ConsentFlags} [options.consent=0] - Bitwise consent flags to use for the group
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Object>} New device group
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def add_device_group(name, description="", amtonly=False, features=0, consent=0, timeout=None):
        raise NotImplementedError()

    '''* 
     * Remove an existing device group
     * @param {string} meshid - Unique id of device group
     * @param {boolean} [isname=False] - treat "meshid" as a name instead of an id
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def remove_device_group(meshid, isname=False, timeout=None):
        raise NotImplementedError()

    '''* 
     * Edit an existing device group
     * @param {string} meshid - Unique id of device group
     * @param {Object} [options={}]
     * @param {boolean} [options.isname=False] - treat "meshid" as a name instead of an id
     * @param {string} [options.name=None] - New name for group
     * @param {boolean} [options.description=None] - New description
     * @param {constants.MeshFeatures} [options.flags=None] - Features to enable on the group
     * @param {constants.ConsentFlags} [options.consent=None] - Which consent flags to use for the group
     * @param {string[]} [options.invite_codes=None] - Create new invite codes
     * @param {boolean} [options.backgroundonly=False] - Flag for invite codes
     * @param {boolean} [options.interactiveonly=False] - Flag for invite codes
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def edit_device_group(meshid, isname=False, name=None, description=None, flags=None, consent=None, invite_codes=None, backgroundonly=False, interactiveonly=False, timeout=None):
        raise NotImplementedError()

    '''* 
     * Move a device from one group to another
     * @param {string|array} nodeids - Unique node id(s)
     * @param {string} meshid - Unique mesh id
     * @param {boolean} [isname=False] - treat "meshid" as a name instead of an id
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Boolean>} true on success
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def move_to_device_group(nodeids, meshid, isname=False, timeout=None):
        raise NotImplementedError()

    '''* 
     * Add a user to an existing mesh
     * @param {string|array} userids - Unique user id(s)
     * @param {string} meshid - Mesh to add the given user to
     * @param {Object} [options={}]
     * @param {boolean} [options.isname=False] - Read meshid as a name rather than an id
     * @param {constants.MeshRights} [options.rights=0] - Bitwise mask for the rights on the given mesh
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<object>} Object showing which were added correctly and which were not, along with their result messages
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def add_users_to_device_group(userids, meshid, isname=False, rights=0, timeout=None):
        raise NotImplementedError()

    '''* 
     * Remove users from an existing mesh
     * @param {string|array} userids - Unique user id(s)
     * @param {string} meshid - Mesh to add the given user to
     * @param {boolean} [isname=False] - Read meshid as a name rather than an id
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<Object>} Object showing which were removed correctly and which were not
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def remove_users_from_device_group(userids, meshid, isname=False, timeout=None):
        raise NotImplementedError()

    '''*
     * Broadcast a message to all users or a single user
     * @param {string} message - Message to broadcast
     * @param {string} [userid=None] - Optional user to which to send the message
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @return {Promise<boolean>} True if successful
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def broadcast(message, userid=None, timeout=None):
        raise NotImplementedError()

    '''* Get all info for a given device. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {string} nodeid - Unique id of desired node
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise} Object containing all meaningful device info
     * @throws {ValueError} `Invalid device id` if device is not found
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def device_info(nodeid, timeout=None):
        raise NotImplementedError()


    '''* Edit properties of an existing device
     * @param {string} nodeid - Unique id of desired node
     * @param {Object} [options={}]
     * @param {string} [options.name=None] - New name for device
     * @param {string} [options.description=None] - New description for device
     * @param {string|string[]} [options.tags=None] - New tags for device
     * @param {constants.Icon} [options.icon=None] - New icon for device
     * @param {constants.ConsentFlags} [options.consent=None] - New consent flags for device
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} True if successful
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def edit_device(nodeid, name=None, description=None, tags=None, icon=None, consent=None, timeout=None):
        raise NotImplementedError()

    '''* Run a command on any number of nodes. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {string|string[]} nodeids - Unique ids of nodes on which to run the command
     * @param {string} command - Command to run
     * @param {Object} [options={}]
     * @param {boolean} [options.powershell=False] - Use powershell to run command. Only available on Windows.
     * @param {boolean} [options.runasuser=False] - Attempt to run as a user instead of the root permissions given to the agent. Fall back to root if we cannot.
     * @param {boolean} [options.runasuseronly=False] - Error if we cannot run the command as the logged in user.
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<Object>} Object containing mapped output of the commands by device
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def run_command(nodeids, command, powershell=False, runasuser=False, runasuseronly=False, timeout=None):
        raise NotImplementedError()

    '''* Get a terminal shell on the given device
     * @param {string} nodeid - Unique id of node on which to open the shell
     * @param {boolean} [unique=False] - true: Create a unique {@link _Shell}. Caller is responsible for cleanup. False: Use a cached {@link _Shell} if available, otherwise create and cache.
     * @returns {Promise<_Shell>} Newly created and initialized {@link _Shell} or cached {@link _Shell} if unique is False and a shell is currently active
     '''
    async def shell(nodeid, unique=False):
        raise NotImplementedError()

    '''* Get a smart terminal shell on the given device
     * @param {string} nodeid - Unique id of node on which to open the shell
     * @param {regex} regex - Regex to watch for to signify that the shell is ready for new input.
     * @param {boolean} [unique=False] - true: Create a unique {@link _SmartShell}. Caller is responsible for cleanup. False: Use a cached {@link _SmartShell} if available, otherwise create and cache.
     * @returns {Promise<_SmartShell>} Newly created and initialized {@link _SmartShell} or cached {@link _SmartShell} if unique is False and a smartshell with regex is currently active
     '''
    async def smart_shell(nodeid, regex, unique=False):
        raise NotImplementedError()

    '''* Wake up given devices
     * @param {string|string[]} nodeids - Unique ids of nodes which to wake
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} True if successful
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def wake_devices(nodeids, timeout=None):
        raise NotImplementedError()

    '''* Reset given devices
     * @param {string|string[]} nodeids - Unique ids of nodes which to reset
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} True if successful
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def reset_devices(nodeids, timeout=None):
        raise NotImplementedError()

    '''* Sleep given devices
     * @param {string|string[]} nodeids - Unique ids of nodes which to sleep
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} True if successful
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def sleep_devices(nodeids, timeout=None):
        raise NotImplementedError()

    '''* Power off given devices
     * @param {string|string[]} nodeids - Unique ids of nodes which to power off
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} True if successful
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def power_off_devices(nodeids, timeout=None):
        raise NotImplementedError()

    '''* List device shares of given node. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {string} nodeid - Unique id of nodes of which to list shares
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<Object[]>} Array of objects representing device shares
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def list_device_shares(nodeid, timeout=None):
        raise NotImplementedError()

    '''* Add device share to given node. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {string} nodeid - Unique id of nodes of which to list shares
     * @param {string} name - Name of guest with which to share
     * @param {Object} [options={}]
     * @param {constants.SharingType} [options.type=constants.SharingType.desktop] - Type of share thise should be
     * @param {constants.ConsentFlags} [options.consent=None] - Consent flags for share. Defaults to "notify" for your given constants.SharingType
     * @param {number|Date} [options.start=new Date()] - When to start the share
     * @param {number|Date} [options.end=None] - When to end the share. If None, use duration instead
     * @param {number} [options.duration=60*60] - Duration in seconds for share to exist
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<Object>} Info about the newly created share
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def add_device_share(nodeid, name, type=constants.SharingType.desktop, consent=None, start=None, end=None, duration=60*60, timeout=None):
        raise NotImplementedError()

    '''* Remove a device share
     * @param {string} nodeid - Unique node from which to remove the share
     * @param {string} shareid - Unique share id to be removed
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} true if successful
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def remove_device_share(nodeid, shareid, timeout=None):
        raise NotImplementedError()

    '''* Open url in browser on device. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.
     * @param {string} nodeid - Unique node from which to remove the share
     * @param {string} url - url to open
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} true if successful
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {Error} `Failed to open url` if failure occurs
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def device_open_url(nodeid, url, timeout=None):
        raise NotImplementedError()

    '''* Display a message on remote device.
     * @param {string} nodeid - Unique node from which to remove the share
     * @param {string} message - message to display
     * @param {string} [title="MeshCentral"] - message title
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} true if successful
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     '''
    async def device_message(nodeid, message, title="MeshCentral", timeout=None):
        raise NotImplementedError()

    '''* Popup a toast a message on remote device.
     * @param {string|string[]} nodeids - Unique node from which to remove the share
     * @param {string} message - message to display
     * @param {string} [title="MeshCentral"] - message title
     * @param {number?} [timeout=None] - duration in milliseconds to wait for a response before throwing an error
     * @returns {Promise<boolean>} true if successful
     * @throws {ServerError} Error text from server if there is a failure
     * @throws {SocketError} Info about socket closure
     * @throws {TimeoutError} Command timed out
     * @todo This function returns true even if it fails, because the server tells us it succeeds before it actually knows, then later tells us it failed, but it's hard to find that because it looks exactly like a success.
     '''
    async def device_toast(nodeids, message, title="MeshCentral", timeout=None):
        raise NotImplementedError()

    '''* Fire off an interuser message. This is a fire and forget api, we have no way of checking if the user got the message.
     * @param {serializable} data - Any sort of serializable data you want to send to the user
     * @param {Object} [options={}]
     * @param {string} [options.session=None] - Direct session to send to. Use this after you have made connection with a specific user session.
     * @param {string} [options.user=None] - Send message to all sessions of a particular user. One of these must be set.
     * @throws {ValueError} Value error if neither user nor session are given.
     * @throws {SocketError} Info about socket closure
     '''
    def interuser(data, session=None, user=None):
        raise NotImplementedError()

    '''* Upload a stream to a device. This creates an _File and destroys it every call. If you need to upload multiple files, use {@link Session#file_explorer} instead.
     * @param {string} nodeid - Unique id to upload stream to
     * @param {ReadableStream} source - ReadableStream from which to read data
     * @param {string} target - Path which to upload stream to on remote device
     * @param {boolean} [unique_file_tunnel=False] - true: Create a unique {@link _Files} for this call, which will be cleaned up on return, else use cached or cache {@link _Files}
     * @returns {Promise<Object>} - {result: bool whether upload succeeded, size: number of bytes uploaded}
     '''
    async def upload(nodeid, source, target, unique_file_tunnel=False):
        raise NotImplementedError()

    '''* Friendly wrapper around {@link Session#upload} to upload from a filepath. Creates a ReadableStream and calls upload.
     * @param {string} nodeid - Unique id to upload file to
     * @param {string} filepath - Path from which to read the data
     * @param {string} target - Path which to upload file to on remote device
     * @param {boolean} [unique_file_tunnel=False] - true: Create a unique {@link _Files} for this call, which will be cleaned up on return, else use cached or cache {@link _Files}
     * @returns {Promise<Object>} - {result: bool whether upload succeeded, size: number of bytes uploaded}
     '''
    async def upload_file(nodeid, filepath, target, unique_file_tunnel=False):
        raise NotImplementedError()

    '''* Download a file from a device into a writable stream. This creates an _File and destroys it every call. If you need to upload multiple files, use {@link Session#file_explorer} instead.
     * @param {string} nodeid - Unique id to download file from
     * @param {string} source - Path from which to download from device
     * @param {WritableStream} [target=None] - Stream to which to write data. If None, create new PassThrough stream which is both readable and writable.
     * @param {boolean} [unique_file_tunnel=False] - true: Create a unique {@link _Files} for this call, which will be cleaned up on return, else use cached or cache {@link _Files}
     * @returns {Promise<WritableStream>} The stream which has been downloaded into
     * @throws {Error} String showing the intermediate outcome and how many bytes were downloaded
     '''
    async def download(nodeid, source, target=None, unique_file_tunnel=False):
        raise NotImplementedError()

    '''* Friendly wrapper around {@link Session#download} to download to a filepath. Creates a WritableStream and calls download.
     * @param {string} nodeid - Unique id to download file from
     * @param {string} source - Path from which to download from device
     * @param {string} filepath - Path to which to download data
     * @param {boolean} [unique_file_tunnel=False] - true: Create a unique {@link _Files} for this call, which will be cleaned up on return, else use cached or cache {@link _Files}
     * @returns {Promise<WritableStream>} The stream which has been downloaded into
     '''
    async def download_file(nodeid, source, filepath, unique_file_tunnel=False):
        raise NotImplementedError()

    '''* Create, initialize, and return an _File object for the given node
     * @param {string} nodeid - Unique id on which to open file explorer
     * @param {boolean} [unique=False] - true: Create a unique {@link _Files}. Caller is responsible for cleanup. False: Use a cached {@link _Files} if available, otherwise create and cache.
     * @returns {Promise<_Files>} A newly initialized file explorer.
     '''
    async def file_explorer(nodeid, unique=False):
        raise NotImplementedError()