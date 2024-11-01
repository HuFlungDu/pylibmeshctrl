import sys
import os
import asyncio
thisdir = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.realpath(f"{thisdir}/../src"))
import meshctrl

async def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    url = argv[0]
    user = argv[1]
    password = argv[2]
    async with meshctrl.session.Session(url, user=user, password=password) as s:
        print(await s.list_device_groups(10))

if __name__ == "__main__":
    asyncio.run(main())