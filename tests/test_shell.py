import sys
import os
import asyncio
import meshctrl
import requests

async def test_shell(env):
    async with meshctrl.session.Session(env.mcurl, user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session:
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

                async with admin_session.shell(agent.nodeid) as s:
                    await s.write("ls\n")
                    resp = await s.read(length=4, timeout=1)
                    assert len(resp) == 4, "Got too many bytes in return!"
                    resp = await s.read(timeout=1)
                    assert "meshagent" in resp, "ls listing is incomplete"
                    await s.write("ls\n")
                    resp = ""
                    for i in range(5):
                        # We won't get 99999999 bytes, so this will error if block=False is not working
                        resp += await asyncio.wait_for(s.read(length=99999999, block=False), timeout=5)
                        await asyncio.sleep(1)
                    # But this guaruntees that we still get the data eventually.
                    assert "meshagent" in resp, "ls listing is incomplete"
        finally:
            assert (await admin_session.remove_device_group(mesh.meshid, timeout=10)), "Failed to remove device group"


async def test_smart_shell(env):
    async with meshctrl.session.Session(env.mcurl, user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session:
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

                async with admin_session.smart_shell(agent.nodeid, r"app@.*\$") as ss:
                    assert "meshagent" in await ss.send_command("ls\n", timeout=5), "ls listing is incomplete"
                    # Check that newline is added if the user doesn't add it
                    assert "meshagent" in await ss.send_command("ls", timeout=5), "ls listing is incomplete"
        finally:
            assert (await admin_session.remove_device_group(mesh.meshid, timeout=10)), "Failed to remove device group"