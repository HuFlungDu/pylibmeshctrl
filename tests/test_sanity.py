import sys
import os
import asyncio
thisdir = os.path.dirname(os.path.realpath(__file__))
# sys.path.append(os.path.realpath(f"{thisdir}/../src"))
import meshctrl
import ssl
import requests

async def test_sanity(env):
    async with meshctrl.Session(env.mcurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=True) as s:
        got_pong = asyncio.Event()
        async def _():
            async for raw in s.raw_messages():
                if raw == '{action:"pong"}':
                    got_pong.set()
                    break
        ping_task = None
        async with asyncio.TaskGroup() as tg:
            tg.create_task(asyncio.wait_for(_(), timeout=5))
            tg.create_task(asyncio.wait_for(got_pong.wait(), timeout=5))
            ping_task = tg.create_task(s.ping(timeout=10))
        print("\ninfo ping: {}\n".format(ping_task.result()))
        print("\ninfo user_info: {}\n".format(await s.user_info()))
        print("\ninfo server_info: {}\n".format(await s.server_info()))
        pass

async def test_proxy(env):
    async with meshctrl.Session("wss://" + env.dockerurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=True, proxy=env.proxyurl) as s:
        pass

async def test_ssl(env):
    try:
        async with meshctrl.Session(env.mcurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=False) as s:
            pass
    except* ssl.SSLCertVerificationError:
        pass
    else:
        raise Exception("Invalid SSL certificate accepted")