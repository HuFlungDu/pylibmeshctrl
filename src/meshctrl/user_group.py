from . import constants
import datetime

class UserGroup(object):
    '''
    Object to represent a user group. This object is a rough wrapper; it is not guarunteed to be up to date with the state on the server, for instance.

    Args:
        ugrpid (str): id of the user group on the server
        session (~meshctrl.session.Session): Parent session used to run commands
        name (str|None): Mesh name as it is shown on the meshcentral server
        description (str|None): Mesh description as it is shown on the meshcentral server. Also accepted as desc.
        domain (str|None): Domain on server to which device is connected.
        links (dict[str, ~meshctrl.types.UserLink]|None): Collection of links for the device group

    Returns:
        :py:class:`Mesh`: Object representing a device group on the meshcentral server.

    Attributes:
        ugrpid (str): id of the device mesh on the server
        name (str|None): Mesh name as it is shown on the meshcentral server
        description (str|None):  Mesh description as it is shown on the meshcentral server
        domain (str|None): Domain on server to which device is connected.
        links (dict[str, ~meshctrl.types.UserLink]|None): Collection of links for the device group
    '''
    def __init__(self, ugrpid, session, name=None, 
                       desc=None, description=None,
                       domain=None, links=None, **kwargs):
        self.ugrpid = ugrpid
        self._session = session
        if links is None:
            links = {}
        self.links = links
        self.name = name
        self.description = description if description is not None else desc
        self.domain = domain
        # In case meshcentral gives us props we don't understand, store them here.
        self._extra_props = kwargs

    @property
    def short_ugrpid(self):
        '''
        ugrpid without "ugrp/" or the included domain
        '''
        return self.ugrpid.split("/")[-1]

    @property
    def id(self):
        '''
        Alias to "ugrpid" to be consistent accross types.
        '''
        return self.ugrpid

    async def add_users(self, userids, timeout=None):
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
        return await self._session.add_users_to_user_group(userids, self.groupid, isname=False, domain=self.domain, timeout=timeout)

    def __str__(self):
        return f"<UserGroup: ugrpid={self.ugrpid} name={self.name} description={self.description} "\
               f"domain={self.domain} links={self.links}>"
    def __repr__(self):
        return f"UserGroup(ugrpid={repr(self.ugrpid)}, session={repr(self._session)}, name={repr(self.name)}, description={repr(self.description)}, "\
               f"domain={repr(self.domain)}, links={repr(self.links)}, **{repr(self._extra_props)})"