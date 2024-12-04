import sys
import os
import asyncio
import meshctrl
import requests
import random
import io
thisdir = os.path.dirname(os.path.realpath(__file__))

async def test_admin(env):
    async with meshctrl.Session(env.mcurl, user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session,\
               meshctrl.Session(env.mcurl, user="privileged", password=env.users["privileged"], ignore_ssl=True) as privileged_session:
        admin_users = await admin_session.list_users(timeout=10)
        print("\ninfo list_users: {}\n".format(admin_users))
        try:
            no_users = await privileged_session.list_users(timeout=10)
        except* meshctrl.exceptions.ServerError as e:
            assert e.exceptions[0].args[0] == "Access denied"
        else:
            assert len(no_users.keys()) == 0, "non-admin has admin acess"

        admin_sessions = await admin_session.list_user_sessions(timeout=10)
        print("\ninfo list_user_sessions: {}\n".format(admin_sessions))
        try:
            no_sessions = await privileged_session.list_user_sessions(timeout=10)
        except* meshctrl.exceptions.ServerError as e:
            assert e.exceptions[0].args[0] == "Access denied"
        else:
            assert len(no_sessions.keys()) == 0, "non-admin has admin acess"

        assert len(admin_users) == len(env.users.keys()), "Admin cannot see correct number of users"
        assert len(admin_sessions) == 2, "Admin cannot see correct number of oser sessions"


async def test_users(env):
    try:
        async with meshctrl.Session(env.mcurl[3:], user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session:
            pass
    except* ValueError:
        pass
    else:
        raise Exception("Connected with bad URL")
    try:
        async with meshctrl.Session(env.mcurl, user="admin", ignore_ssl=True) as admin_session:
            pass
    except* meshctrl.exceptions.MeshCtrlError:
        pass
    else:
        raise Exception("Connected with no password")
    async with meshctrl.Session(env.mcurl+"/", user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session,\
               meshctrl.Session(env.mcurl, user="privileged", password=env.users["privileged"], ignore_ssl=True) as privileged_session,\
               meshctrl.Session(env.mcurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=True) as unprivileged_session:

        assert len(await admin_session.list_users(timeout=10)) == 3, "Wrong number of users"

        assert await admin_session.add_user("test", "test", email="test@email.com", timeout=10), "Failed to create user"
        assert await admin_session.add_user("test2", randompass=True, email="test2@email.com", emailverified=True, resetpass=True, realname="test2", phone="555555555", rights=0, timeout=10), "Failed to create user"

        try:
            await unprivileged_session.add_user("nope", "nope", timeout=10)
        except:
            pass
        else:
            raise Exception("Unprivileged user created a user")

        assert len(await admin_session.list_users(timeout=10)) == 5, "Wrong number of users"

        assert await admin_session.edit_user("user//test", email="test@email.com", emailverified=True, resetpass=True, realname="test", phone="555555555", rights=0, timeout=10), "Failed to edit user"
        assert await admin_session.edit_user("user//test2", email="test2@email.com", emailverified=False, timeout=10), "Failed to edit user"

        assert await admin_session.remove_user("user//test", timeout=10), "Failed to remove user"
        assert await admin_session.remove_user("user//test2", timeout=10), "Failed to remove user"

        assert len(await admin_session.list_users(timeout=10)) == 3, "Failed to remove user"

async def test_login_token(env):
    async with meshctrl.Session(env.mcurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=True) as s:
        token = await s.add_login_token("test", expire=1, timeout=10)
        print("\ninfo add_login_token: {}\n".format(token))

        async with meshctrl.Session(env.mcurl, user=token["tokenUser"], password=token["tokenPass"], ignore_ssl=True) as s2:
            assert (await s2.user_info())["_id"] == (await s.user_info())["_id"], "Login token logged into wrong account"
        # Wait for the login token to expire
        await asyncio.sleep(65)

        try:
            async with meshctrl.Session(env.mcurl, user=token["tokenUser"], password=token["tokenPass"], ignore_ssl=True) as s2:
                pass
        except:
            pass
        else:
            raise Exception("User logged in with expired token!")

        token = await s.add_login_token("test2", timeout=10)
        token2 = await s.add_login_token("test3", timeout=10)
        print("\ninfo add_login_token_no_expire: {}\n".format(token))
        async with meshctrl.Session(env.mcurl, user=token["tokenUser"], password=token["tokenPass"], ignore_ssl=True) as s2:
            assert (await s2.user_info())["_id"] == (await s.user_info())["_id"], "Login token logged into wrong account"

        r = await s.list_login_tokens(timeout=10)
        print("\ninfo list_login_tokens: {}\n".format(r))
        assert len(r) == 2, "Wrong number of tokens"
        assert "tokenPass" not in r[0], "Retrieved tokens include password"

        r = await s.remove_login_token(token["name"], timeout=10)
        print("\ninfo remove_login_token: {}\n".format(r))
        assert len(await s.remove_login_token([token2["name"]], timeout=10)) == 0, "Residual login tokens"

async def test_mesh_device(env):
    async with meshctrl.Session(env.mcurl, user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session,\
               meshctrl.Session(env.mcurl, user="privileged", password=env.users["privileged"], ignore_ssl=True) as privileged_session,\
               meshctrl.Session(env.mcurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=True) as unprivileged_session:
        # Test creating a mesh
        mesh = await admin_session.add_device_group("test", description="This is a test group", amtonly=False, features=0, consent=0, timeout=10)
        print("\ninfo add_device_group: {}\n".format(mesh))
        assert mesh.meshid, "Mesh failed to create"
        assert len(mesh.links.keys()), "Mesh created without any users"
        assert "user//admin" in mesh.links, "Mesh created with wrong user links"

        # Used to move a device into later
        mesh2 = await admin_session.add_device_group("test2", description="This is a test2 group", amtonly=False, features=0, consent=0, timeout=10)

        # Test editing a device group
        assert await admin_session.edit_device_group(mesh.meshid, name="new_test", description="New description", flags=meshctrl.constants.MeshFeatures.all, consent=meshctrl.constants.ConsentFlags.all, invite_codes=True, timeout=10), "Failed to edit device group"
        try:
            await unprivileged_session.edit_device_group(mesh.meshid, description="New description2", timeout=2)
        except* meshctrl.exceptions.ServerError as e:
            assert e.exceptions[0].args[0] == "Access denied"
        # The server just ignores this command if you don't have permissions, so accept timeout as a good response.
        except* asyncio.TimeoutError:
            pass
        else:
            raise Exception("Unprivileged user could modify device group")

        # Test invite codes. Kinda.
        assert await admin_session.edit_device_group(mesh.meshid, invite_codes=["aoeu", "asdf"], backgroundonly=True, interactiveonly=True, timeout=10), "Failed to edit device group"
        # Test editing a group by name
        assert await admin_session.edit_device_group("new_test", isname=True, name=mesh.name, consent=meshctrl.constants.ConsentFlags.none, timeout=10), "Failed to edit device group by name"

        # Test adding users to device group
        r = await admin_session.add_users_to_device_group((await privileged_session.user_info())["_id"], mesh.meshid, rights=meshctrl.constants.MeshRights.fullrights, timeout=5)
        print("\ninfo add_users_to_device_group: {}\n".format(r))

        assert r[(await privileged_session.user_info())["_id"]]["success"], "Failed to add user to group"

        #Test adding users by device group name
        await admin_session.add_users_to_device_group([(await unprivileged_session.user_info())["_id"]], mesh2.name, isname=True, rights=meshctrl.constants.MeshRights.fullrights, timeout=5)
        await admin_session.remove_users_from_device_group([(await unprivileged_session.user_info())["_id"]], mesh2.name, isname=True, timeout=10)
        
        # Test getting device groups for each user.
        r = await admin_session.list_device_groups(timeout=10)
        print("\ninfo list_device_groups: {}\n".format(r))

        assert len(r) == 2, "Incorrect number of groups"
        assert len(await privileged_session.list_device_groups(timeout=10)) == 1, "Incorrect number of groups"
        assert len(await unprivileged_session.list_device_groups(timeout=10)) == 0, "Unprivileged account has access to group it should not"

        assert r[0].description == "New description", "Description either failed to change, or was changed by a user without permission to do so"

        with env.create_agent(mesh.short_meshid) as agent:
            # Test agent added to device group being propagated correctly
            # Create agent isn't so good at waiting for the agent to show in the sessions. Give it a couple seconds to appear.
            for i in range(3):
                try:
                    r = await admin_session.list_devices(timeout=10)
                    print("\ninfo list_devices: {}\n".format(r))
                    assert len(r) == 1, "Incorrect number of agents connected"
                except:
                    if i == 2:
                        raise
                    await asyncio.sleep(1)
                else:
                    break
            assert len(await privileged_session.list_devices(timeout=10)) == 1, "Incorrect number of agents connected"
            assert len(await unprivileged_session.list_devices(timeout=10)) == 0, "Unprivileged account has access to agent it should not"

            r = await admin_session.list_devices(details=True, timeout=10)
            print("\ninfo list_devices_details: {}\n".format(r))

            r = await admin_session.list_devices(group=mesh.name, timeout=10)
            print("\ninfo list_devices_group: {}\n".format(r))

            r = await admin_session.list_devices(meshid=mesh.meshid, timeout=10)
            print("\ninfo list_devices_meshid: {}\n".format(r))

            # Test editing device info propagating correctly
            assert await admin_session.edit_device(agent.nodeid, name="new_name", description="New Description", tags="device", consent=meshctrl.constants.ConsentFlags.all, timeout=10), "Failed to edit device info"

            assert (await privileged_session.device_info(agent.nodeid, timeout=10)).name == "new_name", "New name did not propagate to other sessions"

            assert await admin_session.edit_device(agent.nodeid, consent=meshctrl.constants.ConsentFlags.none, timeout=10), "Failed to edit device info"

            # Test run_commands
            r = await admin_session.run_command(agent.nodeid, "ls", timeout=10)
            print("\ninfo run_command: {}\n".format(r))
            assert "meshagent" in r[agent.nodeid]["result"], "ls gave incorrect data"
            assert "meshagent" in (await privileged_session.run_command(agent.nodeid, "ls", timeout=10))[agent.nodeid]["result"], "ls gave incorrect data"

            # Test run commands with ndividual device permissions
            try:
                await unprivileged_session.run_command(agent.nodeid, "ls", timeout=10)
            except* (meshctrl.exceptions.ServerError, ValueError):
                pass
            else:
                raise Exception("Unprivileged user has access to device it should not")

            try:
                await unprivileged_session.device_info(agent.nodeid, timeout=10)
            except* ValueError:
                pass
            else:
                raise Exception("Unprivileged user has access to device it should not")

            assert (await admin_session.add_users_to_device((await unprivileged_session.user_info())["_id"], agent.nodeid, meshctrl.constants.MeshRights.norights)), "Failed to add user to device"

            try:
                await unprivileged_session.run_command(agent.nodeid, "ls", ignore_output=True, timeout=10)
            except* meshctrl.exceptions.ServerError:
                pass
            else:
                raise Exception("Unprivileged user has access to device it should not")

            # Test getting individual device info
            r = await unprivileged_session.device_info(agent.nodeid, timeout=10)
            print("\ninfo device_info: {}\n".format(r))

            # This device info includes the mesh ID of the device, even though the user doesn't have acces to that mesh. That's odd.
            # assert r.meshid is None, "Individual device is exposing its meshid"

            assert r.links[(await unprivileged_session.user_info())["_id"]]["rights"] == meshctrl.constants.DeviceRights.norights, "Unprivileged user has too many rights!"

            assert (await admin_session.add_users_to_device([(await unprivileged_session.user_info())["_id"]], agent.nodeid, meshctrl.constants.DeviceRights.remotecontrol|meshctrl.constants.DeviceRights.agentconsole|meshctrl.constants.DeviceRights.remotecommands)), "Failed to modify user's permissions"

            assert (await unprivileged_session.device_info(agent.nodeid, timeout=10)).links[(await unprivileged_session.user_info())["_id"]]["rights"] == meshctrl.constants.DeviceRights.remotecontrol|meshctrl.constants.DeviceRights.agentconsole|meshctrl.constants.DeviceRights.remotecommands, "Adding permissions did not update unprivileged user."

            # For now, this expects no response. If we ever figure out why the server isn't sending console information te us when it should, fix this.
            # assert "meshagent" in (await unprivileged_session.run_command(agent.nodeid, "ls", timeout=10))[agent.nodeid]["result"], "ls gave incorrect data"
            await unprivileged_session.run_command(agent.nodeid, "ls", timeout=10)

            assert await admin_session.move_to_device_group(agent.nodeid, mesh2.meshid, timeout=5), "Failed to move mesh to new device group"

            try:
                await privileged_session.device_info(agent.nodeid, timeout=10)
            except* ValueError:
                pass
            else:
                raise Exception("Privileged user has access to device after it was moved to a new mesh")

            assert await admin_session.move_to_device_group([agent.nodeid], mesh.name, isname=True, timeout=5), "Failed to move mesh to new device group by name"

            # For now, this expects no response. If we ever figure out why the server isn't sending console information te us when it should, fix this.
            # assert "meshagent" in (await unprivileged_session.run_command(agent.nodeid, "ls", timeout=10))[agent.nodeid]["result"], "ls gave incorrect data"
            try:
                await unprivileged_session.run_command(agent.nodeid, "ls", timeout=10)
            except:
                raise Exception("Failed to run command on device after it was moved to a new mesh while having individual device permissions")

        r = await admin_session.remove_users_from_device_group((await privileged_session.user_info())["_id"], mesh.meshid, timeout=10)
        print("\ninfo remove_users_from_device_group: {}\n".format(r))
        assert (await admin_session.remove_users_from_device(agent.nodeid, (await unprivileged_session.user_info())["_id"], timeout=10)), "Failed to remove user from device"

        assert (r[(await privileged_session.user_info())["_id"]]["success"]), "Failed to remove user from devcie group"

        assert (await admin_session.remove_device_group(mesh.meshid, timeout=10)), "Failed to remove device group"
        assert (await admin_session.remove_device_group(mesh2.name, isname=True, timeout=10)), "Failed to remove device group"
        assert not (await admin_session.add_users_to_device_group((await privileged_session.user_info())["_id"], mesh.meshid, rights=meshctrl.constants.MeshRights.fullrights, timeout=5))[(await privileged_session.user_info())["_id"]]["success"], "Added user to device group which doesn't exist?"

async def test_user_groups(env):
    async with meshctrl.Session(env.mcurl, user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session,\
               meshctrl.Session(env.mcurl, user="privileged", password=env.users["privileged"], ignore_ssl=True) as privileged_session,\
               meshctrl.Session(env.mcurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=True) as unprivileged_session:
        
        user_group = await admin_session.add_user_group("test", description="aoeu")
        print("\ninfo add_user_group: {}\n".format(user_group))
        user_group2 = await admin_session.add_user_group("test2", description="aoeu")
        r = await admin_session.list_user_groups(timeout=10)
        assert len(r) == 2, "Wrong number of user groups"
        print("\ninfo list_user_groups: {}\n".format(r))
        assert (await privileged_session.list_user_groups(timeout=10))[0].description == None, "User has access to group they should not"

        r = await admin_session.add_users_to_user_group((await privileged_session.user_info())["_id"], user_group.id, timeout=10)
        print("\ninfo add_users_to_user_group: {}\n".format(r))
        assert r[(await privileged_session.user_info())["_id"].split("/")[-1]]["success"], "Failed to add user to user group"
        assert (await admin_session.add_users_to_user_group([(await unprivileged_session.user_info())["_id"]], user_group.id.split("/")[-1], timeout=10))[(await unprivileged_session.user_info())["_id"].split("/")[-1]]["success"], "Failed to add user to user group"
        r = await privileged_session.list_user_groups(timeout=10)
        print("\ninfo list_user_groups_non_owner: {}\n".format(r))

        # Non owners just don't get to see the description.
        # assert r[0].description == "aoeu", "Failed to add user to user group"
        assert await admin_session.remove_user_from_user_group((await privileged_session.user_info())["_id"], user_group.id, timeout=10)
        assert await admin_session.remove_user_from_user_group((await unprivileged_session.user_info())["_id"], user_group.id.split("/")[-1], timeout=10)

        assert await admin_session.remove_user_group(user_group.id)
        assert await admin_session.remove_user_group(user_group2.id.split("/")[-1])

async def test_events(env):
    async with meshctrl.Session(env.mcurl, user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session:
        await admin_session.list_events()
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
                async with meshctrl.Session(env.mcurl, user="privileged", password=env.users["privileged"], ignore_ssl=True) as privileged_session:
                    
                    # assert len(await privileged_session.list_events()) == 0, "non-admin user has access to admin events"

                    await admin_session.run_command(agent.nodeid, "ls", timeout=10)

                    events = await privileged_session.list_events(nodeid=agent.nodeid)
                    admin_events = await admin_session.list_events(nodeid=agent.nodeid)
                    # For some reason, this lets you get these. Probably a bug.
                    # assert len(events) == 0, "User has access to events on device on which they are not a user"
                    assert len(admin_events) > 0, "Admin didn't get events from running a command"

                    await admin_session.add_users_to_device_group((await privileged_session.user_info())["_id"], mesh.meshid, rights=meshctrl.constants.MeshRights.fullrights, timeout=5)
                    events = await privileged_session.list_events()
                    admin_events = await admin_session.list_events()

                    events = await admin_session.list_events()
                    assert len(events) > 1, "Missed some events"
                    assert len(await admin_session.list_events(limit=1)) == 1, "Event limiter gave wrong number of events"

                    events = await privileged_session.list_events(userid=(await admin_session.user_info())["_id"])
                    admin_events = await admin_session.list_events(userid=(await privileged_session.user_info())["_id"])
                    assert len(events) != len(admin_events), "Failed to filter events based on user id"
        finally:
            assert (await admin_session.remove_device_group(mesh.meshid, timeout=10)), "Failed to remove device group"
            
async def test_interuser(env):
    async with meshctrl.Session(env.mcurl, user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session,\
               meshctrl.Session(env.mcurl, user="privileged", password=env.users["privileged"], ignore_ssl=True) as privileged_session:
        got_message = asyncio.Event()
        async def _():
            async for message in admin_session.events({"action": "interuser"}):
                print("\ninfo interuser_message: {}\n".format(message))
                assert message["data"] == "ping", "Got wrong interuser message"
                await admin_session.interuser("pong", session=message["sessionid"])
                break

        async def __():
            async for message in privileged_session.events({"action": "interuser"}):
                assert message["data"] == "pong", "Got wrong interuser message"
                got_message.set()
                break

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_())
            tg.create_task(__())
            # Interuser only works with username, not id
            tg.create_task(privileged_session.interuser("ping", user=(await admin_session.user_info())["_id"].split("/")[-1]))
            tg.create_task(asyncio.wait_for(got_message.wait(), 5))

async def test_session_files(env):
    async with meshctrl.Session(env.mcurl, user="admin", password=env.users["admin"], ignore_ssl=True) as admin_session:
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

                randdata = random.randbytes(2000000)
                upfilestream = io.BytesIO(randdata)
                downfilestream = io.BytesIO()
                os.makedirs(os.path.join(thisdir, "data"), exist_ok=True)
                with open(os.path.join(thisdir, "data", "test"), "wb") as outfile:
                    outfile.write(randdata)

                r = await admin_session.upload(agent.nodeid, upfilestream, f"{pwd}/test", timeout=5)
                print("\ninfo files_upload: {}\n".format(r))
                assert r["result"] == "success", "Upload failed"
                assert r["size"] == len(randdata), "Uploaded wrong number of bytes"

                r = await admin_session.upload_file(agent.nodeid, os.path.join(thisdir, "data", "test"), f"{pwd}/test2", timeout=5)
                print("\ninfo files_upload: {}\n".format(r))
                assert r["result"] == "success", "Upload failed"
                assert r["size"] == len(randdata), "Uploaded wrong number of bytes"

                s = await admin_session.download(agent.nodeid, f"{pwd}/test", timeout=5)
                assert s.read() == randdata, "Downloaded bad data"

                await admin_session.download(agent.nodeid, f"{pwd}/test", downfilestream, timeout=5)
                assert downfilestream.read() == randdata, "Downloaded bad data"

                await admin_session.download_file(agent.nodeid, f"{pwd}/test2", os.path.join(thisdir, "data", "test"), timeout=5)

                with open(os.path.join(thisdir, "data", "test"), "rb") as infile:
                    assert infile.read() == randdata, "Downloaded bad data into file"

                r = await admin_session.upload_file(agent.nodeid, os.path.join(thisdir, "data", "test"), f"{pwd}/test2", unique_file_tunnel=True, timeout=5)
                
                assert r["result"] == "success", "Upload failed"
                assert r["size"] == len(randdata), "Uploaded wrong number of bytes"

                await admin_session.download_file(agent.nodeid, f"{pwd}/test2", os.path.join(thisdir, "data", "test"), unique_file_tunnel=True, timeout=5)
                with open(os.path.join(thisdir, "data", "test"), "rb") as infile:
                    assert infile.read() == randdata, "Downloaded bad data into file"
        finally:
            assert (await admin_session.remove_device_group(mesh.meshid, timeout=10)), "Failed to remove device group"