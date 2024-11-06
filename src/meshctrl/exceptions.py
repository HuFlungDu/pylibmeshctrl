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