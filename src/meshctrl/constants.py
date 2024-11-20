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
class DeviceRights(enum.IntFlag):
    """
    Bitwise flags for device rights
    Piggy backs on rights for a mesh, but has differet "all" rights.
    """
    #: Give user no rights
    norights = 0
    #: Remote control access
    remotecontrol = MeshRights.remotecontrol
    #: Agent console access
    agentconsole = MeshRights.agentconsole
    serverfiles = MeshRights.serverfiles
    #: Wake device from sleep
    wakedevices = MeshRights.wakedevices
    #: Add notes to the device/mesh
    notes = MeshRights.notes
    #: Only view the desktop; no control
    desktopviewonly = MeshRights.desktopviewonly
    #: No terminal access
    noterminal = MeshRights.noterminal
    #: No file access
    nofiles = MeshRights.nofiles
    #: No AMT access
    noamt = MeshRights.noamt
    limiteddesktop = MeshRights.limiteddesktop
    limitedevents = MeshRights.limitedevents
    chatnotify = MeshRights.chatnotify
    uninstall = MeshRights.uninstall
    #: Allow to send commands to the device
    remotecommands = MeshRights.remotecommands
    #: All rights
    fullrights = remotecontrol|agentconsole|serverfiles|wakedevices|notes|chatnotify|uninstall|remotecommands

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

@document_enum
class AgentType(enum.IntEnum):
    """
    Which type of agent this is. Taken from meshcentral.js obj.meshAgentsArchitectureNumbers 
    """
    UNKNOWN = 0
    CONSOLE_WIN_X86_32 = 1
    CONSOLE_WIN_X86_64 = 2
    SERVICE_WIN_X86_32 = 3
    SERVICE_WIN_X86_64 = 4
    SERVICE_LINUX_X86_32 = 5
    SERVICE_LINUX_X86_64 = 6
    SERVICE_LINUX_MIPS = 7
    SERVICE_LINUX_XEN_X86_32 = 8
    SERVICE_LINUX_ARM5 = 9
    SERVICE_LINUX_ARM_PLUGPC = 10
    SERVICE_MACOS_X86_32 = 11
    SERVICE_ANDROID_X86_32 = 12
    SERVICE_ANDROID_POGOPLUG = 13
    SERVICE_ANDROID_APK = 14
    SERVICE_LINUX_POKY_x86_32 = 15
    SERVICE_MACOS_X86_64 = 16
    SERVICE_CHROMEOS = 17
    SERVICE_LINUX_POKY_x86_64 = 18
    SERVICE_LINUX_X86_32_NOKVM = 19
    SERVICE_LINUX_X86_64_NOKVM = 20
    CONSOLE_WIN_MINICORE_X86_32 = 21
    SERVICE_WIN_MINICORE_X86_32 = 22
    SERVICE_NODEJS = 23
    SERVICE_LINUX_ARM_LINARO = 24
    SERVICE_LINUX_ARM_HARDFLOAT = 25
    SERVICE_LINUX_ARM64 = 26
    SERVICE_LINUX_ARM_HARDFLOAT_2 = 27
    SERVICE_LINUX_MIPS24KC = 28
    SERVICE_MACOS_ARM64 = 29
    SERVICE_FREEBSD_X86_64 = 30
    SERVICE_LINUX_ARM64_2 = 32
    SERVICE_OPENWRT_X86_64 = 33
    ASSISTANT_LINUX = 34 # This is labeled as "windows" in meshcentral.js, but its properties indicate it is for linux.
    SERVICE_LINUX_ARMADA370_HARDFLOAT = 35
    SERVICE_OPENWRT_X86_64_2 = 36
    SERVICE_OPENBSD_X86_64 = 37
    SERVICE_LINUX_MIPSEL24KC = 40
    SERVICE_LINUX_CORTEX_A53 = 41
    CONSOLE_WIN_ARM64 = 42
    SERVICE_WIN_ARM64 = 43
    SERVICE_WIN_X86_32_UNSIGNED = 10003
    SERVICE_WIN_X86_64_UNSIGNED = 10004
    SERVICE_MACOS_UNIVERSAL_64 = 10005
    ASSISTANT_WINDOWS = 10006
    COMMAND_WIN_X86_32 = 11000
    COMMAND_WIN_X86_64 = 11001

@document_enum
class MeshType(enum.IntEnum):
    """
    Which type of Mesh this is.
    """
    #: AMT devices only
    AMT = 1
    #: Controllable using an agent
    AGENT = 2
    #: Control only local devices; no agent
    LOCAL = 3


@document_enum
class AgentCapabilities(enum.IntFlag):
    """
    Flags of capabilities an agent can have. Taken from meshagent.h MeshCommand_AuthInfo_CapabilitiesMask from meshagent repo
    """

    #: Can control the desktop
    DESKTOP = enum.auto()
    #: Can use a terminal, or `~meshctrl.shell.Shell` in our case
    TERMINAL = enum.auto()
    #: Can use a files tunnel, or `~meshctrl.files.Files` in our case
    FILES = enum.auto()
    # ???
    CONSOLE = enum.auto()
    #: Agent can use the javascript core. This should be set for any recent agents, older ones might not have it set
    JAVASCRIPT = enum.auto()
    #: Device was created in a temporary manner, and will be destroyed once it disconnects
    TEMPORARY = enum.auto()
    #: Agent is using the recovery core
    RECOVERY = enum.auto()
    #: Reserved for future use
    RESERVED = enum.auto()
    #: Agent can handle compressed streams (?)
    COMPRESSION = enum.auto()

@document_enum
class InteruserScope(enum.StrEnum):
    """
    String constants used to determine the scope of a received :py:class:`~meshctrl.types.InteruserMessage`
    """

    #: The message was sent to your username
    user = enum.auto()

    #: The message was sent to this specific session.
    session = enum.auto()

@document_enum
class Protocol(enum.IntEnum):
    """
    Protocol to use for a tunnel. There are others, but these are what we implement.
    """
    #: Terminal tunnel protocol
    TERMINAL = 1
    #: File explorer tunnel protocol
    FILES = 5

@document_enum
class FileType(enum.IntEnum):
    """
    Type numbers used for file types on meshcentral agent.
    """
    #: Root drive (Windows)
    DRIVE = 1
    #: Directory
    DIRECTORY = 2
    #: File
    FILE = 3

