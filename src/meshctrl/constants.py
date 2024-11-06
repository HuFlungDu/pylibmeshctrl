import enum
try:
    from enum_tools.documentation import document_enum
except:
    def document_enum(cls, *args, **kwargs):
        return cls

@document_enum
class UserRights(enum.IntFlag):
    """
    Bitwise flags for user rights

    """

    #: Give user no rights
    norights = 0
    #: Allow backup of mesh database
    backup = enum.auto() 
    #: User can add or remove users
    manageusers = enum.auto()
    #: User can restore the database from a backup
    restore = enum.auto()
    #: User can upload files to server storage
    fileaccess = enum.auto()
    #: User can update server version
    update = enum.auto()
    #: User is disabled
    locked = enum.auto()
    #: User cannot create new meshes
    nonewgroups = enum.auto() #
    notools = enum.auto() #
    #: User can create user groups
    usergroups = enum.auto() #
    #: User can record desktop sessions
    recordings = enum.auto()
    locksettings = enum.auto()
    #: User has full rights
    fullrights = backup|manageusers|restore|fileaccess|update|locked|nonewgroups|notools|usergroups|recordings|locksettings

@document_enum
class MeshRights(enum.IntFlag):
    """
    Bitwise flags for mesh rights
    Pulls double duty as rights for a connected device
    """
    #: Give user no rights
    norights = 0
    #: Edit the group
    editgroup = enum.auto()
    #: Add/remove users
    manageusers = enum.auto()
    #: Add/remove devices
    managedevices = enum.auto()
    #: Remote control access
    remotecontrol = enum.auto()
    #: Agent console access
    agentconsole = enum.auto()
    serverfiles = enum.auto()
    #: Wake device from sleep
    wakedevices = enum.auto()
    #: Add notes to the device/mesh
    notes = enum.auto()
    #: Only view the desktop; no control
    desktopviewonly = enum.auto()
    #: No terminal access
    noterminal = enum.auto()
    #: No file access
    nofiles = enum.auto()
    #: No AMT access
    noamt = enum.auto()
    limiteddesktop = enum.auto()
    limitedevents = enum.auto()
    chatnotify = enum.auto()
    uninstall = enum.auto()
    #: Disable remote desktop
    noremotedesktop = enum.auto()
    #: Allow to send commands to the device
    remotecommands = enum.auto()
    #: Reset or poweroff device
    resetpoweroff = enum.auto()
    #: All rights
    fullrights = 0xFFFFFFFF

@document_enum
class ConsentFlags(enum.IntFlag):
    none = 0
    desktopnotify = enum.auto()
    terminalnotify = enum.auto()
    filesnotify = enum.auto()
    desktopprompt = enum.auto()
    terminalprompt = enum.auto()
    filesprompt = enum.auto()
    desktopprivacybar = enum.auto()
    all = desktopnotify|terminalnotify|filesnotify|desktopprompt|terminalprompt|filesprompt|filesprompt

@document_enum
class MeshFeatures(enum.IntFlag):
    none = 0
    autoremove = enum.auto()
    hostnamesync = enum.auto()
    recordsessions = enum.auto()
    all = autoremove|hostnamesync|recordsessions

@document_enum
class SharingType(enum.StrEnum):
    """
    String constants used to determine which type of device share to create
    """
    desktop = enum.auto()
    terminal = enum.auto()

@document_enum
class SharingTypeInt(enum.IntEnum):
    """
    Internal enum used to map SHARINGTYPE to the number used by MeshCentral
    """
    desktop = enum.auto()
    terminal = enum.auto()

@document_enum
class Icon(enum.IntEnum):
    """
    Which icon to use for a device
    """
    desktop = enum.auto()
    laptop = enum.auto()
    phone = enum.auto()
    server = enum.auto()
    htpc = enum.auto()
    router = enum.auto()
    embedded = enum.auto()
    virtual = enum.auto()