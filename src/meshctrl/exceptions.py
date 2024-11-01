class MeshCtrlError(Exception):
    pass

# /** Represents an error thrown from the server
#  * @extends Error
#  */
class ServerError(MeshCtrlError):
    pass

# /** Represents an error in the websocket
#  * @extends Error
#  */

class SocketError(MeshCtrlError):
    pass

# /** Represents that a command timed out
#  * @extends Error
#  */
class TimeoutError(MeshCtrlError):
    pass
