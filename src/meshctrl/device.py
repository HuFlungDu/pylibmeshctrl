from . import constants
import datetime

class Device(object):
    '''
    Object to represent a device. This object is a rough wrapper; it is not guarunteed to be up to date with the state on the server, for instance.

    Args:
        nodeid (str): id of the device on the server
        session (~meshctrl.session.Session): Parent session used to run commands
        agent (~meshctrl.types.Agent|dict|None): Information about the agent. Meshcentral returns this data in an unreadable way, so if the dict doesn't match :py:class:`~meshctrl.types.Agent`, we will attempt to convert to our format.
        name (str|None): Device name as it is shown on the meshcentral server
        description (str|None): Device description as it is shown on the meshcentral server. Also accepted as desc.
        tags (list[str]|None): tags associated with device.
        created_at (datetime.Datetime|int|None): Time at which device mas created. Also accepted as agct.
        computer_name (str|None): Device name as reported from the agent. This may be different from name. Also accepted as rname.
        icon (~meshctrl.constants.Icon): Icon displayed on the website
        mesh (~meshctrl.mesh.Mesh|None): Mesh object under which this device exists. Is None for individual device access.
        meshtype (~meshctrl.constants.MeshType|None): Type of mesh this device is connected to. Also accepted as mtype.
        meshname (str|None): Name of the mesh to which this device is connected. Also accepted as groupname.
        domain (str|None): Domain on server to which device is connected.
        host (str): reachable hostname of device. Not meaningful for agent meshes.
        ip (str): IP from which device connected.
        connected: (bool): Whether the device is currently connected. Also accepted as conn.
        powered_on (bool): Whether the device is currently powered on. Also accepted as pwr.
        os_description (str|None): Description of the underlying OS. Also accepted as osdesc.
        lastaddr (str|None): IP from which the agent most recently connected. This may be set even if ip is not.
        lastconnect (datetime.Datetime|int|None): Last time at which the agent was connected to the server
        links (dict[str, ~meshctrl.types.UserLink]|None): Collection of links for the device,
        details (dict[str, dict]|None): Extra details about the device. These are not well defined, but are filled by calling :py:meth:`~meshctrl.session.Session.list_devices` with `details=True`.

    Returns:
        :py:class:`Device`: Object representing a device on the meshcentral server.

    Attributes:
        nodeid (str): id of the device on the server
        agent (~meshctrl.types.Agent|dict|None): Information about the agent. Meshcentral returns this data in an unreadable way, so if the dict doesn't match :py:class:`~meshctrl.types.Agent`, we will attempt to convert to our format.
        name (str|None): Device name as it is shown on the meshcentral server
        description (str|None): Device description as it is shown on the meshcentral server.
        tags (list[str]): tags associated with device.
        computer_name (str|None): Device name as reported from the agent. This may be different from name. Also accepted as rname.
        icon (~meshctrl.constants.Icon): Icon displayed on the website
        mesh (~meshctrl.mesh.Mesh|None): Mesh object under which this device exists. Is None for individual device access.
        meshtype (~meshctrl.constants.MeshType|None): Type of mesh this device is connected to. Also accepted as mtype.
        meshname (str|None): Name of the mesh to which this device is connected. Also accepted as groupname.
        domain (str|None): Domain on server to which device is connected.
        host (str): reachable hostname of device. Not meaningful for agent meshes.
        ip (str): IP from which device connected.
        connected: (bool): Whether the device is currently connected. Also accepted as conn.
        powered_on (bool): Whether the device is currently powered on. Also accepted as pwr.
        os_description (str|None): Description of the underlying OS. Also accepted as osdesc.
        lastaddr (str|None): IP from which the agent most recently connected. This may be set even if ip is not.
        lastconnect (datetime.Datetime|None): Last time at which the agent was connected to the server
        links (dict[str, ~meshctrl.types.UserLink]|None): Collection of links for the device
        details (dict[str, dict]): Extra details about the device. These are not well defined, but are filled by calling :py:meth:`~meshctrl.session.Session.list_devices` with `details=True`.
    '''
    def __init__(self, nodeid, session, agent=None,
                       name=None, desc=None, description=None,
                       tags=None,
                       agct=None, created_at=None,
                       rname=None, computer_name=None, icon=constants.Icon.desktop,
                       mesh=None, mtype=None, meshtype=None, groupname=None, meshname=None,
                       domain=None, host=None, ip=None, conn=None, connected=None,
                       pwr=None, powered_on=None,
                       osdesc=None, os_description=None, lastaddr=None, lastconnect=None,
                       links=None, details=None, **kwargs):
        self.nodeid = nodeid
        self._session = session
        if links is None:
            links = {}
        self.links = links
        if ("ver" in agent):
            agent = {
                "version": agent["ver"],
                "id": agent["id"],
                "capabilities": agent["caps"]
            }
        self.agent = agent
        self.name = name
        self.computer_name = computer_name if computer_name is not None else rname
        self.icon = icon
        self.mesh = mesh
        self.meshtype = meshtype if meshtype is not None else mtype
        self.meshname = meshname if meshname is not None else groupname
        self.domain = domain
        self.host = host
        self.ip = ip
        self.connected = bool(connected if connected is not None else conn)
        self.powered_on = bool(powered_on if powered_on is not None else pwr)
        self.description = description if description is not None else desc
        self.os_description = os_description if os_description is not None else osdesc
        self.tags = tags if tags is not None else []
        self.details = details if details is not None else {}

        created_at = created_at if created_at is not None else agct
        if not isinstance(created_at, datetime.datetime) and created_at is not None:
            try:
                created_at = datetime.datetime.fromtimestamp(created_at)
            except (OSError, ValueError):
                # Meshcentral returns in miliseconds, while fromtimestamp, and most of python, expects the argument in seconds. Try seconds frist, then translate from ms if it fails.
                # This doesn't work for really early timestamps, but I don't expect that to be a problem here.
                created_at = datetime.datetime.fromtimestamp(created_at/1000.0)

        self.created_at = created_at

        if not isinstance(lastconnect, datetime.datetime) and lastconnect is not None:
            try:
                lastconnect = datetime.datetime.fromtimestamp(lastconnect)
            except (OSError, ValueError):
                # Meshcentral returns in miliseconds, while fromtimestamp, and most of python, expects the argument in seconds. Try seconds frist, then translate from ms if it fails.
                # This doesn't work for really early timestamps, but I don't expect that to be a problem here.
                lastconnect = datetime.datetime.fromtimestamp(lastconnect/1000.0)

        self.lastconnect = lastconnect
        self.lastaddr = lastaddr

        # In case meshcentral gives us props we don't understand, store them here.
        self._extra_props = kwargs

    async def add_users(self, userids, rights=None, timeout=None):
        '''
        Add a user to an existing node

        Args:
            userids (str|list[str]): Unique user id(s)
            rights (~meshctrl.constants.DeviceRights): Bitwise mask for the rights on the given device
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        return await self._session.add_users_to_device(userids, self.nodeid, domain=self.domain, rights=rights, timeout=timeout)

    async def remove_users(self, userids, timeout=None):
        '''
        Remove users from an this node

        Args:
            userids (str|list[str]): Unique user id(s)
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True on success, raise otherwise

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        return await self._session.remove_users_from_device(self.nodeid, userids, timeout=timeout)

    async def move_to_device_group(self, meshid, isname=False, timeout=None):
        '''
        Move this device another device group

        Args:
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
        return await self._session.remove_users_from_device(self.nodeid, meshid, isname=isname, timeout=timeout)

    async def info(self, timeout=None):
        '''
        Get all info for this device. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            ~meshctrl.device.Device: Object representing the state of the device. This will be a new device, it will not update this device.

        Raises:
            ValueError: `Invalid device id` if device is not found
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        return await self._session.device_info(self.nodeid, timeout=timeout)

    async def edit(self, name=None, description=None, tags=None, icon=None, consent=None, timeout=None):
        '''
        Edit properties of this device

        Args:
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
        return await self._session.edit_device(self.nodeid, name=name, description=description, tags=tags, icon=icon, consent=consent, timeout=timeout)

    async def run_command(self, command, powershell=False, runasuser=False, runasuseronly=False, ignore_output=False, timeout=None):
        '''
        Run a command on this device. WARNING: Non namespaced call. Calling this function again before it returns may cause unintended consequences.

        Args:
            command (str): Command to run
            powershell (bool): Use powershell to run command. Only available on Windows.
            runasuser (bool): Attempt to run as a user instead of the root permissions given to the agent. Fall back to root if we cannot.
            ignore_output (bool): Don't bother trying to get the output. Every device will return an empty string for its result.
            runasuseronly (bool): Error if we cannot run the command as the logged in user.
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            ~meshctrl.types.RunCommandResponse: Output of command

        Raises:
            :py:class:`~meshctrl.exceptions.ServerError`: Error text from server if there is a failure
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            ValueError: `Invalid device id` if device is not found
            asyncio.TimeoutError: Command timed out
         '''
        return (await self._session.run_command(self.nodeid, command, powershell=False, runasuser=False, runasuseronly=False, ignore_output=False, timeout=None))[self.nodeid]

    async def shell(self):
        '''
        Get a terminal shell on this device

        Returns:
            :py:class:`~meshctrl.shell.Shell`: Newly created :py:class:`~meshctrl.shell.Shell`
         '''
        return await self._session.shell(self.nodeid)


    async def smart_shell(self, regex):
        '''
        Get a smart terminal shell on this device

        Args:
            regex (regex): Regex to watch for to signify that the shell is ready for new input.

        Returns:
            :py:class:`~meshctrl.shell.SmartShell`: Newly created :py:class:`~meshctrl.shell.SmartShell`
         '''
        return await self._session.smart_shell(self.nodeid, regex)


    async def wake(self, timeout=None):
        '''
        Wake up this device

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''

        return await self._session.wake_devices(self.nodeid, timeout=timeout)

    async def reset(self, timeout=None):
        '''
        Reset device

        Args:
            nodeids (str|list[str]): Unique ids of nodes which to reset
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
         '''
        return await self._session.reset_devices(self.nodeid, timeout=timeout)

    async def sleep(self, timeout=None):
        '''
        Sleep device

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        return await self._session.sleep_devices(self.nodeid, timeout=timeout)

    async def power_off(self, timeout=None):
        ''' Power off device

        Args:
            timeout (int): duration in seconds to wait for a response before throwing an error

        Returns:
            bool: True if successful

        Raises:
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        return await self._session.power_off_devices(self.nodeid, timeout=timeout)

    @property
    def short_nodeid(self):
        '''
        nodeid without "node/" or the included domain
        '''
        return self.nodeid.split("/")[-1]

    @property
    def id(self):
        '''
        Alias to "nodeid" to be consistent accross types.
        '''
        return self.nodeid

    def __str__(self):
        return f"<Device: nodeid={self.nodeid} name={self.name} description={self.description} computer_name={self.computer_name} icon={self.icon} "\
               f"mesh={self.mesh} meshtype={self.meshtype} meshname={self.meshname} domain={self.domain} host={self.host} ip={self.ip} "\
               f"tags={self.tags} details={self.details} created_at={self.created_at} lastaddr={self.lastaddr} lastconnect={self.lastconnect} "\
               f"connected={self.connected} powered_on={self.powered_on} os_description={self.os_description} links={self.links} _extra_props={self._extra_props}>"
    def __repr__(self):
        return f"Device(nodeid={repr(self.nodeid)}, session={repr(self._session)}, name={repr(self.name)}, description={repr(self.description)}, computer_name={repr(self.computer_name)}, icon={repr(self.icon)}, "\
               f"mesh={repr(self.mesh)}, meshtype={repr(self.meshtype)}, meshname={repr(self.meshname)}, domain={repr(self.domain)}, host={repr(self.host)}, ip={repr(self.ip)}, "\
               f"tags={repr(self.tags)}, details={repr(self.details)} created_at={repr(self.created_at)} lastaddr={repr(self.lastaddr)} lastconnect={repr(self.lastconnect)} "\
               f"connected={repr(self.connected)}, powered_on={repr(self.powered_on)}, os_description={repr(self.os_description)}, links={repr(self.links)}, **{repr(self._extra_props)})"
