"""Entry point: python -m onecta_modbus (or the onecta-modbus console script)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

import aiohttp
from aiohttp import web

from . import __version__
from .bridge import Bridge
from .config import Config
from .modbus import start_server
from .onecta import Onecta
from .web import WebUI

_LOGGER = logging.getLogger("onecta_modbus")


async def run(config: Config) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": f"onecta-modbus/{__version__}"}) as session:
        onecta = Onecta(config.data_dir, session)
        bridge = Bridge(config, onecta)

        modbus = await start_server(bridge, config.modbus_host, config.modbus_port)
        runner = web.AppRunner(WebUI(bridge, config.modbus_port, config.web_password).app(), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, config.web_host, config.web_port).start()
        _LOGGER.info("Modbus TCP on %s:%d, web UI on http://%s:%d", config.modbus_host, config.modbus_port,
                     config.web_host, config.web_port)

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)

        worker = asyncio.create_task(bridge.run())
        await stop.wait()
        _LOGGER.info("Stopping")
        worker.cancel()
        modbus.close()
        await modbus.wait_closed()
        await runner.cleanup()


def main() -> None:
    config = Config()
    logging.basicConfig(level=config.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
