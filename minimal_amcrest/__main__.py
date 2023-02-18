import asyncio
import datetime

import aiohttp
from halo import Halo

from .digest import DigestAuth

USERNAME = "admin"
PASSWORD = "FIXME"


async def main():
    timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=15)

    spinner = Halo(text="Polling", spinner="dots")
    spinner.start()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        auth = DigestAuth(USERNAME, PASSWORD, session)

        response = await auth.request(
            "GET",
            f"http://doorbell.internal/cgi-bin/eventManager.cgi?action=attach&codes=[CallNoAnswered]&heartbeat=5",
        )
        response.raise_for_status()

        try:
            async for data, _ in response.content.iter_chunks():
                data = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                blocks = [b.strip() for b in data.split("--myboundary\n")]
                blocks = ["\n".join(b.split("\n")[3:]) for b in blocks if len(b) > 0]

                for block in blocks:
                    if "CallNoAnswered" in block:
                        spinner.succeed(
                            f"Doorbell Pressed @ {datetime.datetime.now().isoformat()}\n{block}"
                        )
                        spinner.start()
                    elif "Heartbeat" not in block:
                        spinner.warn(block)
                        spinner.start()

        except Exception as ex:
            spinner.fail(str(ex))


if __name__ == "__main__":
    asyncio.run(main())
