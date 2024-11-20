from flask import Flask, json, request
import requests
import tempfile
import base64
import os
import subprocess
import time

AGENT_URL_TEMPLATE = "https://{}/meshagents?id=6"
SETTINGS_URL_TEMPLATE = "https://{}/meshsettings?id={}"

api = Flask(__name__)

agents = {}

# if not os.path.exists(os.path.join(mesh_dir, "meshagent")):
#     os.makedirs(meshtemp)
#     subprocess.check_call(["wget", AGENT_URL, "-O", os.path.join(meshtemp, "meshagent")])
#     subprocess.check_call(["wget", SETTINGS_URL, "-O", os.path.join(meshtemp, "meshagent.msh")])
#     subprocess.check_call(["chmod", "+x", os.path.join(meshtemp, "meshagent")])
#     shutil.copytree(meshtemp, mesh_dir)
#     subprocess.check_call(["chown", "-R", f"{user}:{user}", mesh_dir])

@api.route('/add-agent', methods=['POST'])
def add_agent():
    api.logger.info("text")
    AGENT_URL = AGENT_URL_TEMPLATE.format(request.json["url"])
    SETTINGS_URL = SETTINGS_URL_TEMPLATE.format(request.json["url"], request.json["meshid"])
    d = tempfile.mkdtemp()
    agent_path = os.path.join(d, "meshagent")
    msh_path = os.path.join(d, "meshagent.msh")
    with open(agent_path, "wb") as outfile:
        for chunk in requests.get(AGENT_URL, stream=True, verify=False).iter_content(chunk_size=16*1024):
            outfile.write(chunk)
    with open(msh_path, "wb") as outfile:
        for chunk in requests.get(SETTINGS_URL, stream=True, verify=False).iter_content(chunk_size=16*1024):
            outfile.write(chunk)
    os.chmod(agent_path, 0o0777)
    os.chmod(msh_path, 0o0777)
    # Generates a certificate if we don't got one
    subprocess.call([agent_path, "-connect"])
    agent_hex = subprocess.check_output([agent_path, '-exec', "console.log(require('_agentNodeId')());process.exit()"]).strip().decode()
    agent_id = base64.b64encode(bytes.fromhex(agent_hex)).decode().replace("+", "@").replace("/", "$")
    p = subprocess.Popen(["stdbuf", "-o0", agent_path, "connect"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=d)
    agents[agent_id] = {"process": p, "id": agent_id}
    text = ""
    start = time.time()
    while time.time() - start < 5:
        text += p.stdout.read1().decode("utf-8")
        api.logger.info(text)
        if "Connected." in text:
            break
        time.sleep(.1)
    else:
        raise Exception(f"Failed to start agent: {text}")
    return {"id": agent_id}

@api.route('/remove-agent/<agentid>', methods=['POST'])
def remove_agent(agentid):
    agents[agentid]["process"].kill()
    return ""

@api.route('/', methods=['GET'])
def slash():
    return [_["id"] for _ in agents]

if __name__ == '__main__':
    api.run()