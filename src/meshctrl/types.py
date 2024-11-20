'''
This module attempts to define the various structures of objects returned by meshcentral calls.
These types are expected, but not guarunteed, as the meshcentral API is not well defined.
'''

import typing
import collections.abc
from . import constants

class UserLink(typing.TypedDict):
    '''
    Represents a link to a user account
    '''

    rights: constants.MeshRights|constants.DeviceRights
    '''User's rights on the containing object'''

    name: str
    '''Username of the user this link references'''

class ListUsersResponseItem(typing.TypedDict):
    ''' 
    Item contained in response from :py:func:`~meshctrl.session.Session.list_users`
    '''

    _id: str
    '''User's ID'''

    name: str
    '''User's username'''

    creation: int
    '''When the user was created. UTC timestamp'''

    links: dict[str, list[UserLink]]
    '''Set of links connected to this user. str is the ID of the thing referenced, the type of which is hinted at by the beginning of the string. These describe numerous things, the enumeration of which is beyond this documentation'''

class AddUsersToDeviceGroupResponse(typing.TypedDict):
    '''
    Response proffered when a user is added to a device group
    '''

    success: bool
    '''Whether the user was added successfully'''

    message: str
    '''Any interesting information about adding the user. "Added user {username}" on success, otherwise defined by server'''

class RemoveUsersFormDeviceGroupResponse(AddUsersToDeviceGroupResponse):
    '''
    Response proffered when a user is removed from a device group
    '''
    pass

class DeviceGroup(typing.TypedDict):
    '''
    Device group information
    '''

    meshid: str
    '''ID of the created device group'''

    links: dict[str, list[UserLink]]
    '''Users of this device group, and their rights'''

class Agent(typing.TypedDict):
    '''
    Information about an agent running on a machine
    '''

    version: int
    '''Agent version'''

    id: constants.AgentType
    '''Type of agent this is'''

    capabilities: constants.AgentCapabilities
    '''Capabilities of this agent. This can change over time based on the connection state of the agent'''

class AddDeviceGroupResponse(typing.TypedDict):
    '''
    Response proffered when device group is added
    '''

    meshid: str
    '''ID of the created device group'''

    links: dict[str, list[UserLink]]
    '''Users of this device group, and their rights'''

class RunCommandResponse(typing.TypedDict):
    '''
    Response item from run_command execution
    '''

    complete: bool
    '''Whether the command completed correctly'''

    command: str
    '''The command which was run'''

    result: str
    '''Output of command'''

class AddUsersToUserGroupResponse(typing.TypedDict):
    '''
    Response item from add_users_to_user_group execution
    '''

    success: bool
    '''Whether the user was added successfully'''

    message: str
    '''Message from server if user was not added correctly'''

class LoginToken(typing.TypedDict):
    '''
    Login token created on the server
    '''

    name: str
    '''Name of the token'''

    tokenUser: str
    '''Username substitute of the token'''

    tokenPass: str
    '''Password substitute for the token'''

    created: int
    '''UTC timestamp representing when the token was created. In milliseconds'''

    expire: int
    '''UTC timestamp representing when the token expires. In milliseconds. 0 means no expirery.'''

class RetrievedLoginToken(typing.TypedDict):
    '''
    Login token created on the server and retrieved. This will not include the password.
    '''

    name: str
    '''Name of the token'''

    tokenUser: str
    '''Username substitute of the token'''

    created: int
    '''UTC timestamp representing when the token was created. In milliseconds'''

    expire: int
    '''UTC timestamp representing when the token expires. In milliseconds. 0 means no expirery.'''

class InteruserMessage(typing.TypedDict):
    '''
    Message received from another user through interuser messaging
    '''

    action: "interuser"
    '''Identifier of event type'''

    sessionid: str
    '''Session from which the message originated'''

    data: str
    '''Any data the user sent'''

    scope: constants.InteruserScope
    '''"user" if the message was sent to your username, "session" if it was sent to this specific session.'''

class FilesLSItem(typing.TypedDict):
    '''
    Dict representing a file or directory on a mesh device, as returned from meshcentral server
    '''

    n: str
    '''Name of file or dir'''

    d: str
    '''UTC timestamp for when the file/directory was edited'''

    t: constants.FileType
    '''Type of file'''

    dt: typing.Optional[str]
    '''Drive type, in the case t == :py:const:`~meshctrl.constants.FileType.DRIVE`'''

    s: typing.Optional[int]
    '''Size of the file if t == :py:const:`~meshctrl.constants.FileType.FILE`'''

    f: typing.Optional[int]
    '''Free bytes on the drive, if t == :py:const:`~meshctrl.constants.FileType.DRIVE`'''