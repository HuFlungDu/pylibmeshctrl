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
        async with asyncio.TaskGroup() as tg:
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

async def test_urlparse():
    # This tests the url port adding necessitated by python-socks. Our test environment doesn't use 443, so this is just a quick sanity test.
    try:
        async with meshctrl.Session("wss://localhost", user="unprivileged", password="Not a real password", ignore_ssl=True) as s:
            pass
    except* asyncio.TimeoutError:
        #We're not running a server, so timeout is our expected outcome
        pass

    # This tests our check for wss/ws url schemes
    try:
        async with meshctrl.Session("https://localhost", user="unprivileged", password="Not a real password", ignore_ssl=True) as s:
            pass
    except* ValueError:
        pass