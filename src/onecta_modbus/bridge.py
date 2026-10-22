"""Coordinator: polls Onecta, serves Modbus reads from the cached state, turns writes into PATCHes."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime

import aiohttp

from .config import Config
from .model import Command, Device
from .modbus import GATEWAY_TARGET_FAILED, ModbusError
from .onecta import ApiError, AuthError, Onecta, RateLimited, read_json, seconds_until_day_reset, write_private_json
from .registers import (
    BY_ADDRESS, HOLDING, REFRESH, STATUS_AUTH_FAILED, STATUS_CLOUD_ERROR, STATUS_NOT_LOGGED_IN, STATUS_OK,
    STATUS_RATE_LIMITED, STATUS_STARTING, UNSUPPORTED, Context,
)

_LOGGER = logging.getLogger(__name__)
MIN_POLL_GAP = 60  # seconds between polls requested from Loxone or the web UI


class Bridge:
    def __init__(self, config: Config, onecta: Onecta):
        self.config = config
        self.onecta = onecta
        self.units_file = config.data_dir / "units.json"
        self.unit_by_gateway: dict[str, int] = {k: int(v) for k, v in read_json(self.units_file).items()}
        self.devices: dict[str, Device] = {}
        self.status = STATUS_STARTING if onecta.logged_in else STATUS_NOT_LOGGED_IN
        self.last_error: str | None = None
        self.last_poll: float | None = None
        self.next_poll_at = 0.0
        self.events: deque[tuple[float, str]] = deque(maxlen=60)
        self._wake = asyncio.Event()
        self._api_lock = asyncio.Lock()
        self._last_written: dict[tuple[int, int], int] = {}
        self._pending: dict[tuple[int, int], int] = {}
        self._flushing: set[tuple[int, int]] = set()
        self.command_times: deque[float] = deque()
        self.commands_blocked = 0

    # ---- bookkeeping ----------------------------------------------------------------

    def log(self, message: str, level: int = logging.INFO) -> None:
        _LOGGER.log(level, message)
        self.events.appendleft((time.time(), message))

    @property
    def gateway_by_unit(self) -> dict[int, str]:
        return {unit: gateway for gateway, unit in self.unit_by_gateway.items()}

    def set_units(self, mapping: dict[str, int]) -> None:
        units = list(mapping.values())
        if len(set(units)) != len(units) or not all(1 <= u <= 247 for u in units):
            raise ValueError("Unit IDs must be unique and between 1 and 247")
        self.unit_by_gateway.update(mapping)
        write_private_json(self.units_file, self.unit_by_gateway)
        self._last_written.clear()
        self.log("Unit IDs changed: " + ", ".join(f"{self.device_name(g)}={u}" for g, u in mapping.items()))

    def reset(self) -> None:
        """Forget the account's devices and unit IDs (after logout / switching accounts)."""
        self.devices = {}
        self.unit_by_gateway = {}
        write_private_json(self.units_file, self.unit_by_gateway)
        self._last_written.clear()
        self._pending.clear()
        self.last_poll = None
        self.last_error = None
        self.next_poll_at = 0.0
        self.status = STATUS_NOT_LOGGED_IN

    def device_name(self, gateway_id: str) -> str:
        device = self.devices.get(gateway_id)
        return device.name if device else gateway_id

    def _assign_units(self) -> None:
        changed = False
        for device in sorted(self.devices.values(), key=lambda d: d.name.lower()):
            if device.gateway_id not in self.unit_by_gateway:
                used = set(self.unit_by_gateway.values())
                self.unit_by_gateway[device.gateway_id] = next(u for u in range(1, 248) if u not in used)
                changed = True
        if changed:
            write_private_json(self.units_file, self.unit_by_gateway)

    def poll_interval(self) -> float:
        """Seconds until the next poll: the day/night interval, stretched so polling never
        touches the calls reserved for commands before the daily counter resets."""
        now = datetime.now().time()
        day_start, night_start = self.config.day_start, self.config.night_start
        is_day = day_start <= now < night_start if day_start < night_start else not night_start <= now < day_start
        interval = 60 * (self.config.poll_day_minutes if is_day else self.config.poll_night_minutes)
        slowest = 60 * self.config.max_poll_minutes
        left = self.onecta.rate_limit.day
        if left is None:
            return interval
        spare = left - self.config.command_reserve
        if spare <= 0:
            return max(interval, slowest)
        return min(max(interval, seconds_until_day_reset() / spare), max(interval, slowest))

    # ---- command budget -------------------------------------------------------------

    def commands_last_hour(self) -> int:
        cutoff = time.time() - 3600
        while self.command_times and self.command_times[0] < cutoff:
            self.command_times.popleft()
        return len(self.command_times)

    def command_block_reason(self) -> str | None:
        left = self.onecta.rate_limit.day
        if left is not None and left <= self.config.min_calls_left:
            return f"only {left} Daikin API calls left today"
        if self.commands_last_hour() >= self.config.max_commands_per_hour:
            return f"limit of {self.config.max_commands_per_hour} commands per hour reached"
        return None

    def refresh_block_reason(self) -> str | None:
        left = self.onecta.rate_limit.day
        if left is not None and left <= self.config.command_reserve:
            return f"only {left} Daikin API calls left today, kept for commands"
        return None

    # ---- main loop ------------------------------------------------------------------

    def wake(self) -> None:
        self._wake.set()

    def request_poll(self, delay: float = 0) -> None:
        earliest = (self.last_poll or 0) + MIN_POLL_GAP
        self.next_poll_at = min(self.next_poll_at, max(time.time() + delay, earliest))
        self.wake()

    async def run(self) -> None:
        while True:
            if not (self.onecta.configured and self.onecta.logged_in):
                self.status = STATUS_NOT_LOGGED_IN
                await self._sleep(None)
                continue
            if time.time() >= self.next_poll_at:
                await self.poll()
            await self._sleep(max(0.0, self.next_poll_at - time.time()))

    async def _sleep(self, timeout: float | None) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    async def poll(self) -> None:
        async with self._api_lock:
            try:
                data = await self.onecta.gateway_devices()
            except AuthError as err:
                self.status, self.last_error = STATUS_AUTH_FAILED, str(err)
                self.next_poll_at = float("inf")
                self.log(f"Login problem: {err}", logging.WARNING)
                return
            except RateLimited as err:
                self.status, self.last_error = STATUS_RATE_LIMITED, str(err)
                self.next_poll_at = time.time() + (err.retry_after or 900)
                self.log(str(err), logging.WARNING)
                return
            except (ApiError, aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                self.status, self.last_error = STATUS_CLOUD_ERROR, str(err) or type(err).__name__
                self.next_poll_at = time.time() + 120
                self.log(f"Polling Daikin failed: {self.last_error}", logging.WARNING)
                return
        if not self.onecta.logged_in:
            return  # logged out while this poll was in flight: drop the old account's data
        self.devices = {item["id"]: Device(item) for item in data if "id" in item}
        self._assign_units()
        self.status, self.last_error = STATUS_OK, None
        self.last_poll = time.time()
        self.next_poll_at = self.last_poll + self.poll_interval()
        _LOGGER.info("Polled %d device(s); %s API calls left today", len(self.devices), self.onecta.rate_limit.day)

    # ---- Modbus handler -------------------------------------------------------------

    def _context(self, unit: int) -> Context:
        gateway = self.gateway_by_unit.get(unit)
        if gateway is None:
            raise ModbusError(GATEWAY_TARGET_FAILED)
        device = self.devices.get(gateway) or Device({"id": gateway, "managementPoints": []})
        return Context(
            device=device,
            now=datetime.now(),
            status=self.status,
            data_age=None if self.last_poll is None else time.time() - self.last_poll,
            calls_left_day=self.onecta.rate_limit.day,
            calls_left_minute=self.onecta.rate_limit.minute,
            commands_last_hour=self.commands_last_hour(),
            commands_blocked=self.commands_blocked,
        )

    def read(self, unit: int, table: str, address: int, count: int) -> list[int]:
        ctx = self._context(unit)
        words = []
        for offset in range(address + 1, address + count + 1):
            register = BY_ADDRESS.get((table, offset))
            words.append(register.encode(ctx) if register else UNSUPPORTED)
        return words

    def write(self, unit: int, address: int, words: list[int]) -> None:
        self._context(unit)  # validates the unit
        for i, word in enumerate(words):
            key = (unit, address + i + 1)
            if self._last_written.get(key) == word:
                continue  # Loxone re-sends values periodically; only changes count
            self._last_written[key] = word
            self._pending[key] = word
            if key not in self._flushing:
                self._flushing.add(key)
                asyncio.get_running_loop().create_task(self._flush(key))

    async def _flush(self, key: tuple[int, int]) -> None:
        try:
            await asyncio.sleep(self.config.write_debounce)
            word = self._pending.pop(key)
        finally:
            self._flushing.discard(key)
        unit, offset = key
        register = BY_ADDRESS.get((HOLDING, offset))
        gateway = self.gateway_by_unit.get(unit)
        device = self.devices.get(gateway) if gateway else None
        if register is None or register.write is None:
            _LOGGER.debug("Ignoring write to unsupported register HR%d on unit %d", offset, unit)
            return
        if device is None:
            self.log(f"Unit {unit}: write HR{offset} ignored, no data from Daikin yet", logging.WARNING)
            return
        value = register.decode(word)
        result = register.write(device, value)
        if result == REFRESH:
            reason = self.refresh_block_reason()
            if reason:
                self.log(f"{device.name}: refresh via HR{offset} refused, {reason}", logging.WARNING)
            else:
                self.request_poll()
                self.log(f"{device.name}: refresh requested via HR{offset}")
            return
        if not isinstance(result, Command):
            self.log(f"{device.name}: HR{offset} {register.name} = {value:g} not supported by this unit", logging.WARNING)
            return
        if device.current_value(result) == result.value:
            _LOGGER.info("%s: %s already %s, no API call", device.name, register.name, result.value)
            return
        reason = self.command_block_reason()
        if reason:
            self.commands_blocked += 1
            self._last_written.pop(key, None)  # let a later write of the same value try again
            self.log(f"{device.name}: {register.name} = {result.value} NOT sent, {reason}", logging.WARNING)
            return
        if not await self._send(device, register.name, result):
            self._last_written.pop(key, None)

    async def _send(self, device: Device, label: str, command: Command) -> bool:
        async with self._api_lock:
            self.command_times.append(time.time())
            try:
                await self.onecta.patch(device.gateway_id, command)
            except AuthError as err:
                self.status, self.last_error = STATUS_AUTH_FAILED, str(err)
                self.log(f"{device.name}: {label} not sent, login problem: {err}", logging.WARNING)
                return False
            except RateLimited as err:
                self.status, self.last_error = STATUS_RATE_LIMITED, str(err)
                self.log(f"{device.name}: {label} not sent, {err}", logging.WARNING)
                return False
            except (ApiError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                self.log(f"{device.name}: {label} failed: {err or type(err).__name__}", logging.WARNING)
                return False
        device.apply(command)  # optimistic; the next regular poll confirms
        self.log(f"{device.name}: {label} set to {command.value}")
        if self.config.refresh_after_write > 0:
            self.request_poll(self.config.refresh_after_write)
        return True
