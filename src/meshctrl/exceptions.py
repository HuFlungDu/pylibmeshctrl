class MeshCtrlError(Exception):
    """
    Base class for Meshctrl errors
    """
    pass

class ServerError(MeshCtrlError):
    """
    Represents an error thrown from the server
    """
    pass

class SocketError(MeshCtrlError):
    """
    Represents an error in the websocket
    """
    pass

class FileTransferError(MeshCtrlError):
    """
    Represents a failed file transfer

    Attributes:
        stats (dict): {"result" (str): Human readable result, "size" (int): number of bytes successfully transferred}
    """
    def __init__(self, message, stats):
        self.stats = stats

class FileTransferCancelled(FileTransferError):
    """
    Represents a canceled file transfer
    """
    pass