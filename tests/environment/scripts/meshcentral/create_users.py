
import os
import subprocess
import json
thisdir = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(thisdir, "users.json")) as infile:
    users = json.load(infile)
for username, password in users.items():
    subprocess.check_output(["node", "/opt/meshcentral/meshcentral", "--createaccount", username, "--pass", password, "--name", username])


subprocess.check_output(["node", "/opt/meshcentral/meshcentral", "--adminaccount", "admin"])

subprocess.call(["bash", "/opt/meshcentral/startup.sh"])