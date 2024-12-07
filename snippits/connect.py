import asyncio
import json
import websockets
from base64 import b64encode

websocket_url = 'wss://meshcentral_url/control.ashx'
username = 'username'
password = 'password'

def base64_encode(string): # Encode to Base64 encoding.
    return b64encode(string.encode('utf-8')).decode()

class ScriptEndTrigger(Exception):
    pass

# Main class for handling WebSocket communication
class meshcaller_websocket:
    meshsocket = None

    @staticmethod
    async def ws_on_open():
        print('Connection established.')

    @staticmethod
    async def ws_on_close():
        print('Connection closed by remote host.')
        raise ScriptEndTrigger("WebSocket connection closed.")

    async def ws_on_message(self, message):
        try:
            received_response = json.loads(message)
            print(json.dumps(received_response,indent=4))

        except json.JSONDecodeError:
            print("Errored on:", message)
            raise ScriptEndTrigger("Failed to decode JSON message")

    async def ws_send_data(self, message):
        if self.meshsocket is not None:
            print('Sending data to the target server.')
            await self.meshsocket.send(message)
            return

        else:
             raise ScriptEndTrigger("WebSocket connection not established. Unable to send data.")

    async def ws_handler(self, uri, username, password):
        login_string = f'{base64_encode(username)},{base64_encode(password)}'
        ws_headers = {
            'User-Agent': 'MeshCentral API client',
            'x-meshauth': login_string
        }
        print("Trying to connect")

        try:
            async with websockets.connect(uri, extra_headers=ws_headers) as meshsocket:
                self.meshsocket = meshsocket
                await self.ws_on_open()  # Call ws_on_open when connection is established
                
                while True:
                    try:
                        message = await meshsocket.recv()  # Receive message
                        await self.ws_on_message(message)  # Process the message
                    except websockets.ConnectionClosed:
                        await self.ws_on_close()  # Call ws_on_close on disconnection
                        break

        except ScriptEndTrigger as e:
            print(f"WebSocket handler ended: {e}")
        except Exception as e:
            print(f"An error occurred: {e}")

async def main():
    try:
        python_client = meshcaller_websocket()

        websocket_daemon = asyncio.create_task(python_client.ws_handler(
                websocket_url,
                username,
                password
            ))
        
        print("Waiting 1 sec.")
        await asyncio.sleep(1)

        # {'action': 'meshes', 'responseid': 'meshctrl'}

        data_to_send = input("What would you like to send? Enter: ")
        try:
            # Parse the JSON input
            json_data_load = json.loads(data_to_send)
            print("Parsed data:", json_data_load)
            print("Type:", type(json_data_load))
            
            # Optionally send the data if needed
            await python_client.ws_send_data(json.dumps(json_data_load))

            await asyncio.sleep(3)
            raise ScriptEndTrigger("Ending this round.")

        except json.JSONDecodeError:
            print("Invalid JSON format. Please use double quotes for JSON keys and values.")
    
        await asyncio.gather(websocket_daemon)
    except ScriptEndTrigger as e:
        print(e)

# Entry point of the script
if __name__ == "__main__":
    asyncio.run(main())
