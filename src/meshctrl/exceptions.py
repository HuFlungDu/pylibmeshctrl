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
        initialized (asyncio.Event): Event marking if the Session initialization has finished. Wait on this to wait for a connection.
        alive (bool): Whether the session connection is currently alive
        closed (asyncio.Event): Event that occurs when the session closes permanently
    """
    def __init__(self, message, stats):
        self.stats = stats

class FileTransferCancelled(FileTransferError):
    """
    Represents a canceled file transfer
    """
    pass