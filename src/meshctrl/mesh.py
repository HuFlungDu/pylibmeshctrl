from . import constants
import datetime

class Mesh(object):
    '''
    Object to represent a device mesh. This object is a rough wrapper; it is not guarunteed to be up to date with the state on the server, for instance.

    Args:
        meshid (str): id of the device mesh on the server
        session (~meshctrl.session.Session): Parent session used to run commands
        created_at (datetime.Datetime|int): Time at which mesh mas created. Also accepted as creation.
        name (str|None): Mesh name as it is shown on the meshcentral server
        description (str|None): Mesh description as it is shown on the meshcentral server. Also accepted as desc.
        meshtype (~meshctrl.constants.MeshType|None): Type of mesh this device is connected to. Also accepted as mtype.
        creatorid (str): User id of the user who created the mesh.
        creatorname (str): Display name of the user who created the mesh.
        domain (str|None): Domain on server to which device is connected.
        links (dict[str, ~meshctrl.types.UserLink]|None): Collection of links for the device group

    Returns:
        :py:class:`Mesh`: Object representing a device group on the meshcentral server.

    Attributes:
        meshid (str): id of the device mesh on the server
        created_at (datetime.Datetime): Time at which mesh mas created.
        name (str|None): Mesh name as it is shown on the meshcentral server
        description (str|None):  Mesh description as it is shown on the meshcentral server
        meshtype (~meshctrl.constants.MeshType|None): Type of mesh this is.
        creatorid (str|None): User id of the user who created the mesh.
        creatorname (str|None): Display name of the user who created the mesh.
        domain (str|None): Domain on server to which device is connected.
        links (dict[str, ~meshctrl.types.UserLink]|None): Collection of links for the device group
    '''
    def __init__(self, meshid, session, creation=None, created_at=None, name=None, 
                       mtype=None, meshtype=None, creatorid=None, desc=None, description=None,
                       domain=None, creatorname=None, links=None, **kwargs):
        self.meshid = meshid
        self._session = session
        if links is None:
            links = {}
        self.links = links
        self.name = name
        self.meshtype = meshtype if meshtype is not None else mtype
        self.description = description if description is not None else desc
        created_at = created_at if created_at is not None else creation
        if not isinstance(created_at, datetime.datetime) and created_at is not None:
            try:
                created_at = datetime.datetime.fromtimestamp(created_at)
            except OSError:
                # Meshcentral returns in miliseconds, while fromtimestamp, and most of python, expects the argument in seconds. Try seconds frist, then translate from ms if it fails.
                # This doesn't work for really early timestamps, but I don't expect that to be a problem here.
                created_at = datetime.datetime.fromtimestamp(created_at/1000.0)
        self.created_at = created_at
        self.creatorid = creatorid
        self.creatorname = creatorname
        self.domain = domain
        # In case meshcentral gives us props we don't understand, store them here.
        self._extra_props = kwargs

    @property
    def short_meshid(self):
        '''
        meshid without "mesh/" or the included domain
        '''
        return self.meshid.split("/")[-1]

    @property
    def id(self):
        '''
        Alias to "meshid" to be consistent accross types.
        '''
        return self.meshid

    async def add_users(self, userids, rights=0, timeout=None):
        '''
        Add a user to an existing mesh

        Args:
            userids (str|list[str]): Unique user id(s)
            rights (~meshctrl.constants.MeshRights): Bitwise mask for the rights to give to the users
            timeout (int): duration in milliseconds to wait for a response before throwing an error

        Returns:
            dict[str, ~meshctrl.types.AddUsersToDeviceGroupResponse]: Object showing which were added correctly and which were not, along with their result messages. str is userid to map response.

        Raises:    
            :py:class:`~meshctrl.exceptions.SocketError`: Info about socket closure
            asyncio.TimeoutError: Command timed out
        '''
        return await self._session.add_users_to_device_group(userids, self.meshid, isname=False, domain=self.domain, rights=rights, timeout=timeout)

    def __str__(self):
        return f"<Mesh: meshid={self.meshid} name={self.name} description={self.description} created_at={self.created_at} "\
               f"meshtype={self.meshtype} domain={self.domain} "\
               f"created_at={self.created_at} creatorid={self.creatorid} creatorname={self.creatorname} links={self.links}>"
    def __repr__(self):
        return f"Mesh(meshid={repr(self.meshid)}, session={repr(self._session)}, name={repr(self.name)},  description={repr(self.description)}, created_at={repr(self.created_at)}, "\
               f"meshtype={repr(self.meshtype)}, domain={repr(self.domain)}, "\
               f"created_at={repr(self.created_at)}, creatorid={repr(self.creatorid)}, creatorname={repr(self.creatorname)}, links={repr(self.links)}, **{repr(self._extra_props)})"