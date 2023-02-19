import asyncio
import datetime
import signal

import aiohttp
import click
import tomli
from halo import Halo
from voluptuous import Required, Schema

from .digest import DigestAuth

config_schema = Schema(
    {
        "amcrest": {
            Required("host"): str,
            Required("username"): str,
            Required("password"): str,
        },
        "mqtt": {Required("host"): str},
    }
)


cancel = asyncio.Event()


def sigint_handler(signum, frame):
    print("Exiting")
    cancel.set()


signal.signal(signal.SIGINT, sigint_handler)


async def doorbell(host, username, password):
    timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=15)

    spinner = Halo(text="Polling", spinner="dots")
    spinner.start()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        auth = DigestAuth(username, password, session)

        response = await auth.request(
            "GET",
            f"http://{host}/cgi-bin/eventManager.cgi?action=attach&codes=[CallNoAnswered]&heartbeat=5",
        )
        response.raise_for_status()

        try:
            async for data, _ in response.content.iter_chunks():
                if cancel.is_set():
                    spinner.warn("Cancelled")
                    break

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


async def mqtt(host):
    pass


async def async_main(config):
    await asyncio.gather(doorbell(**config["amcrest"]), mqtt(**config["mqtt"]))


@click.command()
@click.option(
    "--config_file",
    "-c",
    required=True,
    type=click.File(mode="rb"),
)
def main(config_file):
    config = config_schema(tomli.load(config_file))

    asyncio.run(async_main(config))


if __name__ == "__main__":
    main()
