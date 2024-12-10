import sys
import os
import asyncio
import meshctrl
import requests
import io
import random

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

                randdata = random.randbytes(2000000)
                upfilestream = io.BytesIO(randdata)
                downfilestream = io.BytesIO()

                pwd = (await admin_session.run_command(agent.nodeid, "pwd", timeout=10))[agent.nodeid]["result"].strip()

                async with admin_session.file_explorer(agent.nodeid) as files:
                    r = await files.upload(upfilestream, f"{pwd}/test", timeout=5)
                    print("\ninfo files_upload: {}\n".format(r))
                    assert r["result"] == "success", "Upload failed"
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

                    r = await files.download(f"{pwd}/test", downfilestream, timeout=5)
                    print("\ninfo files_download: {}\n".format(r))
                    assert r["result"] == "success", "Domnload failed"
                    assert r["size"] == len(randdata), "Downloaded wrong number of bytes"

                    downfilestream.seek(0)
                    assert downfilestream.read() == randdata, "Got wrong data back"
        finally:
            assert (await admin_session.remove_device_group(mesh.meshid, timeout=10)), "Failed to remove device group"






