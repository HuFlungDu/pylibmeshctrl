import enum

class UserRights(enum.IntFlag):
    norights = 0
    backup = enum.auto()
    manageusers = enum.auto()
    restore = enum.auto()
    fileaccess = enum.auto()
    update = enum.auto()
    locked = enum.auto()
    nonewgroups = enum.auto()
    notools = enum.auto()
    usergroups = enum.auto()
    recordings = enum.auto()
    locksettings = enum.auto()
    fullrights = backup|manageusers|restore|fileaccess|\
                update|locked|nonewgroups|notools|usergroups|\
                recordings|locksettings

class MeshRights(enum.IntFlag):
    norights = 0
    editgroup = enum.auto()
    manageusers = enum.auto()
    managedevices = enum.auto()
    remotecontrol = enum.auto()
    agentconsole = enum.auto()
    serverfiles = enum.auto()
    wakedevices = enum.auto()
    notes = enum.auto()
    desktopviewonly = enum.auto()
    noterminal = enum.auto()
    nofiles = enum.auto()
    noamt = enum.auto()
    limiteddesktop = enum.auto()
    limitedevents = enum.auto()
    chatnotify = enum.auto()
    uninstall = enum.auto()
    noremotedesktop = enum.auto()
    remotecommands = enum.auto()
    resetpoweroff = enum.auto()
    fullrights = 0xFFFFFFFF

class ConsentFlags(enum.IntFlag):
    none = 0
    desktopnotify = enum.auto()
    terminalnotify = enum.auto()
    filesnotify = enum.auto()
    desktopprompt = enum.auto()
    terminalprompt = enum.auto()
    filesprompt = enum.auto()
    desktopprivacybar = enum.auto()
    all = desktopnotify|terminalnotify|filesnotify|desktopprompt|terminalprompt|\
          filesprompt|filesprompt

class MeshFeatures(enum.IntFlag):
    none = 0
    autoremove = enum.auto()
    hostnamesync = enum.auto()
    recordsessions = enum.auto()
    all = autoremove|hostnamesync|recordsessions

class SharingType(enum.StrEnum):
    desktop = enum.auto()
    terminal = enum.auto()

class SharingTypeInt(enum.IntEnum):
    desktop = enum.auto()
    terminal = enum.auto()

class Icon(enum.IntEnum):
    desktop = enum.auto()
    laptop = enum.auto()
    phone = enum.auto()
    server = enum.auto()
    htpc = enum.auto()
    router = enum.auto()
    embedded = enum.auto()
    virtual = enum.auto()