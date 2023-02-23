"""
Script to retrieve events from Amcrest doorbell and pass them to MQTT
"""

import asyncio
import signal

import aiohttp
import asyncio_mqtt
import click
import tomli
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


def sigint_handler(*_):
    """Handle SIGINT and signal the async loops to exit"""
    print("Exiting")
    cancel.set()


signal.signal(signal.SIGINT, sigint_handler)

event_queue = asyncio.Queue()


class Doorbell:
    """
    API wrapper for Amcrest doorbell API
    """

    def __init__(self, host, username, password):
        """
        Initialise API
        """
        self.host = host
        self.username = username
        self.password = password

        self._session = None
        self._auth = None

    async def __aenter__(self):
        """Create async http session"""
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=15)
        self._session = aiohttp.ClientSession(timeout=timeout)
        self._auth = DigestAuth(self.username, self.password, self._session)
        return self

    async def __aexit__(self, *err):
        """Close down async http session"""
        self._auth = None
        await self._session.close()
        self._session = None

    async def poll_for_events(self):
        """Long poll for doorbell events"""
        while not cancel.is_set():
            print(f"Connecting to host {self.host}")
            response = await self._auth.request(
                "GET",
                f"http://{self.host}/cgi-bin/eventManager.cgi?"
                "action=attach&codes=[CallNoAnswered]&heartbeat=5",
            )
            response.raise_for_status()

            async for data, _ in response.content.iter_chunks():
                if cancel.is_set():
                    break

                data = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                blocks = [b.strip() for b in data.split("--myboundary\n")]
                blocks = ["\n".join(b.split("\n")[3:]) for b in blocks if len(b) > 0]

                for block in blocks:
                    await event_queue.put("Heartbeat")

                    if "CallNoAnswered" in block:
                        await event_queue.put("Doorbell")

    async def get_system_info(self):
        """Get the system info dict from the doorbell"""
        response = await self._auth.request(
            "GET",
            f"http://{self.host}/cgi-bin/magicBox.cgi?action=getSystemInfo",
        )
        response.raise_for_status()

        entries = [
            line.strip().split("=") for line in (await response.text()).splitlines()
        ]
        return {entry[0]: entry[1] for entry in entries}


async def mqtt(serial, host):
    """Connect the MQTT server and send events to it"""
    reconnect_interval = 5  # In seconds

    while not cancel.is_set():
        try:
            print(f"Connecting to MQTT on {host}")
            async with asyncio_mqtt.Client(
                host,
                will=asyncio_mqtt.Will(
                    f"minimal-amcrest/{serial}/status", "offline", retain=True
                ),
            ) as client:
                await client.publish(
                    f"minimal-amcrest/{serial}/status", "online", retain=True
                )

                while not cancel.is_set():
                    try:
                        event = await asyncio.wait_for(event_queue.get(), 1.0)
                        print(f"Publishing event {event}")
                        await client.publish(f"minimal-amcrest/{serial}/event", event)
                    except asyncio.TimeoutError:
                        continue

                await client.publish(
                    f"minimal-amcrest/{serial}/status", "offline", retain=True
                )
        except asyncio_mqtt.MqttError as error:
            print(f'Error "{error}". Reconnecting in {reconnect_interval} seconds.')
            await asyncio.sleep(reconnect_interval)


async def async_main(config):
    """async main function to create API objects"""
    async with Doorbell(**config["amcrest"]) as doorbell:
        serial = (await doorbell.get_system_info())["serialNumber"]

        await asyncio.gather(doorbell.poll_for_events(), mqtt(serial, **config["mqtt"]))


@click.command()
@click.option(
    "--config_file",
    "-c",
    required=True,
    type=click.File(mode="rb"),
)
def main(config_file):
    """Synchronous main function for click"""
    config = config_schema(tomli.load(config_file))

    asyncio.run(async_main(config))


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
