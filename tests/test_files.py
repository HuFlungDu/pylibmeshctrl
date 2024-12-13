import sys
import os
import asyncio
import meshctrl
import requests
import io
import random
import time

async def test_commands(env):
    async with meshctrl.Session("wss://" + env.dockerurl, user="admin", password=env.users["admin"], ignore_ssl=True, proxy=env.proxyurl) as admin_session:
        mesh = await admin_session.add_device_group("test", description="This is a test group", amtonly=False, features=0, consent=0, timeout=10)
        try:
            with env.create_agent(mesh.short_meshid) as agent:
                # Create agent isn't so good at waiting for the agent to show in the sessions. Give it a couple seconds to appear.
                for i in range(3):
                    try:
                        r = await admin_session.list_devices(timeout=10)
                        assert len(r) == 1, "Incorrect number of agents connected"
                    except:
                        if i == 2:
                            raise
                        await asyncio.sleep(1)
                    else:
                        break

                pwd = (await admin_session.run_command(agent.nodeid, "pwd", timeout=10))[agent.nodeid]["result"].strip()

                async with admin_session.file_explorer(agent.nodeid) as files:
                    # Test mkdir
                    print("\ninfo files_mkdir: {}\n".format(await files.mkdir(f"{pwd}/test", timeout=5)))
                    fs = await files.ls(pwd, timeout=5)
                    # Test ls
                    print("\ninfo files_ls: {}\n".format(fs))
                    for f in fs:
                        if f["n"] == "test" and f["t"] == 2:
                            break
                    else:
                        raise Exception("Created directory not found")

                    print("\ninfo files_rename: {}\n".format(await files.rename(pwd, "test", "test2", timeout=5)))

                    for f in await files.ls(pwd, timeout=5):
                        if f["n"] == "test2" and f["t"] == 2:
                            break
                    else:
                        raise Exception("renamed directory not found")

                    print("\ninfo files_rm: {}\n".format(await files.rm(pwd, f"test2", recursive=False, timeout=5)))
                    for f in await files.ls(pwd, timeout=5):
                        if f["n"] in ["test","test2"]:
                            raise Exception("Deleted directory found")
        finally:
            assert (await admin_session.remove_device_group(mesh.meshid, timeout=10)), "Failed to remove device group"

async def test_os_proxy_bypass():
    os.environ["no_proxy"] = "*"
    import urllib
    import urllib.request
    os_proxies = urllib.request.getproxies()
    meshctrl_proxies = meshctrl.files.urllib.request.getproxies()
    print(f"os_proxies: {os_proxies}")
    print(f"meshctrl_proxies: {meshctrl_proxies}")
    assert meshctrl_proxies.get("no", None) == None, "Meshctrl is using system proxies"
    assert os_proxies.get("no", None) == "*", "System is using meshctrl proxies"
    assert os_proxies != meshctrl_proxies, "Override didn't work"

async def test_upload_download(env):
    async with meshctrl.Session("wss://" + env.dockerurl, user="admin", password=env.users["admin"], ignore_ssl=True, proxy=env.proxyurl) as admin_session:
        mesh = await admin_session.add_device_group("test", description="This is a test group", amtonly=False, features=0, consent=0, timeout=10)
        try:
            with env.create_agent(mesh.short_meshid) as agent:
                # Create agent isn't so good at waiting for the agent to show in the sessions. Give it a couple seconds to appear.
                for i in range(3):
                    try:
                        r = await admin_session.list_devices(timeout=10)
                        assert len(r) == 1, "Incorrect number of agents connected"
                    except:
                        if i == 2:
                            raise
                        await asyncio.sleep(1)
                    else:
                        break

                randdata = random.randbytes(20000000)
                upfilestream = io.BytesIO(randdata)
                downfilestream = io.BytesIO()

                pwd = (await admin_session.run_command(agent.nodeid, "pwd", timeout=10))[agent.nodeid]["result"].strip()

                async with admin_session.file_explorer(agent.nodeid) as files:
                    r = await files.upload(upfilestream, f"{pwd}/test", timeout=5)
                    print("\ninfo files_upload: {}\n".format(r))
                    assert r["result"] == True, "Upload failed"
                    assert r["size"] == len(randdata), "Uploaded wrong number of bytes"
                    for f in await files.ls(pwd, timeout=5):
                        if f["n"] == "test" and f["t"] == meshctrl.constants.FileType.FILE:
                            break
                    else:
                        raise Exception("Uploaded file not found")

                    upfilestream.seek(0)

                    await files.upload(upfilestream, f"{pwd}", name="test2", timeout=5)
                    for f in await files.ls(pwd, timeout=5):
                        if f["n"] == "test2" and f["t"] == meshctrl.constants.FileType.FILE:
                            break
                    else:
                        raise Exception("Uploaded file not found")

                    start = time.perf_counter()
                    r = await files.download(f"{pwd}/test", downfilestream, skip_ws_attempt=True, timeout=5)
                    print("\ninfo files_download: {}\n".format(r))
                    assert r["result"] == True, "Download failed"
                    assert r["size"] == len(randdata), "Downloaded wrong number of bytes"
                    print(f"http download time: {time.perf_counter()-start}")

                    downfilestream.seek(0)
                    assert downfilestream.read() == randdata, "Got wrong data back"
                    downfilestream.seek(0)

                    start = time.perf_counter()
                    r = await files.download(f"{pwd}/test", downfilestream, skip_http_attempt=True, timeout=5)
                    print("\ninfo files_download: {}\n".format(r))
                    assert r["result"] == True, "Download failed"
                    assert r["size"] == len(randdata), "Downloaded wrong number of bytes"
                    print(f"ws download time: {time.perf_counter()-start}")

                    downfilestream.seek(0)
                    assert downfilestream.read() == randdata, "Got wrong data back"
        finally:
            assert (await admin_session.remove_device_group(mesh.meshid, timeout=10)), "Failed to remove device group"






