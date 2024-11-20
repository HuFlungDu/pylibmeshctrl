import sys
import os
import asyncio
thisdir = os.path.dirname(os.path.realpath(__file__))
# sys.path.append(os.path.realpath(f"{thisdir}/../src"))
import meshctrl
import ssl
import requests

async def test_sanity(env):
    async with meshctrl.session.Session(env.mcurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=True) as s:
        print("\ninfo user_info: {}\n".format(await s.user_info()))
        print("\ninfo server_info: {}\n".format(await s.server_info()))
        pass

async def test_ssl(env):
    try:
        async with meshctrl.session.Session(env.mcurl, user="unprivileged", password=env.users["unprivileged"], ignore_ssl=False) as s:
            pass
    except* ssl.SSLCertVerificationError:
        pass
    else:
        raise Exception("Invalid SSL certificate accepted")