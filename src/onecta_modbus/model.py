"""Read-only view on one Onecta gateway device (the JSON from /v1/gateway-devices)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

CLIMATE_TYPES = ("climateControl",)
DHW_TYPES = ("domesticHotWaterTank", "domesticHotWaterFlowThrough")
UNIT_TYPES = ("indoorUnitHydro", "indoorUnit")


@dataclass(frozen=True)
class Command:
    """One PATCH to /gateway-devices/{gateway}/management-points/{mp}/characteristics/{name}."""

    management_point: str
    characteristic: str
    value: Any
    path: str | None = None


def _get(obj: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(obj, dict) or key not in obj:
            return None
        obj = obj[key]
    return obj


class Device:
    """Typed accessors over the raw gateway JSON. The raw dict stays the source of truth."""

    def __init__(self, data: dict):
        self.data = data

    @property
    def gateway_id(self) -> str:
        return self.data["id"]

    @property
    def management_points(self) -> list[dict]:
        return self.data.get("managementPoints", [])

    def management_point(self, types: tuple[str, ...]) -> dict | None:
        matches = [mp for mp in self.management_points if mp.get("managementPointType") in types]
        # Prefer the primary point, e.g. climateControlMainZone over an additional zone.
        matches.sort(key=lambda mp: mp.get("managementPointCategory") != "primary")
        return matches[0] if matches else None

    @property
    def climate(self) -> dict | None:
        return self.management_point(CLIMATE_TYPES)

    @property
    def dhw(self) -> dict | None:
        return self.management_point(DHW_TYPES)

    @property
    def name(self) -> str:
        for mp in (self.climate, self.dhw):
            name = _get(mp, "name", "value")
            if name:
                return name
        return self.data.get("deviceModel", self.gateway_id)

    @property
    def model(self) -> str | None:
        return _get(self.management_point(UNIT_TYPES), "modelInfo", "value")

    @property
    def online(self) -> bool:
        return bool(_get(self.data, "isCloudConnectionUp", "value") is not False)

    @staticmethod
    def value(mp: dict | None, characteristic: str) -> Any:
        return _get(mp, characteristic, "value")

    @staticmethod
    def setpoint(mp: dict | None, mode: str, key: str) -> dict | None:
        return _get(mp, "temperatureControl", "value", "operationModes", mode, "setpoints", key)

    @staticmethod
    def sensor(mp: dict | None, key: str) -> float | None:
        return _get(mp, "sensoryData", "value", key, "value")

    def apply(self, command: Command) -> None:
        """Optimistically store a successful PATCH in the raw JSON."""
        mp = next((m for m in self.management_points if m.get("embeddedId") == command.management_point), None)
        target = _get(mp, command.characteristic)
        if target is None:
            return
        if command.path:
            node = target.get("value")
            for part in command.path.strip("/").split("/"):
                node = node.get(part) if isinstance(node, dict) else None
            if isinstance(node, dict):
                node["value"] = command.value
        else:
            target["value"] = command.value

    def current_value(self, command: Command) -> Any:
        mp = next((m for m in self.management_points if m.get("embeddedId") == command.management_point), None)
        target = _get(mp, command.characteristic)
        if command.path and target is not None:
            return _get(target.get("value"), *command.path.strip("/").split("/"), "value")
        return _get(target, "value")


def round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def setpoint_command(mp: dict | None, mode: str, key: str, value: float) -> Command | None:
    """Clamp and round a requested setpoint to what Daikin reports as allowed."""
    sp = Device.setpoint(mp, mode, key)
    if mp is None or sp is None or sp.get("settable") is False:
        return None
    step = sp.get("stepValue") or 0.5
    value = round(round(value / step) * step, 2)
    if sp.get("minValue") is not None:
        value = max(value, sp["minValue"])
    if sp.get("maxValue") is not None:
        value = min(value, sp["maxValue"])
    if float(value).is_integer():
        value = int(value)
    return Command(mp["embeddedId"], "temperatureControl", value, f"/operationModes/{mode}/setpoints/{key}")


def characteristic_command(mp: dict | None, characteristic: str, value: Any) -> Command | None:
    entry = _get(mp, characteristic)
    if mp is None or entry is None or entry.get("settable") is False:
        return None
    allowed = entry.get("values")
    if allowed is not None and value not in allowed:
        return None
    return Command(mp["embeddedId"], characteristic, value)


def energy(mp: dict | None, purpose: str, period: str, now: datetime) -> float | None:
    """Electrical energy in kWh from Onecta consumptionData.

    d: 24 two-hour slots (12 yesterday, 12 today); m: 24 months (last year, this year).
    """
    series = _get(mp, "consumptionData", "value", "electrical", purpose)
    if not isinstance(series, dict):
        return None

    def total(values: list | None) -> float | None:
        if values is None:
            return None
        known = [v for v in values if v is not None]
        return float(sum(known)) if known else 0.0

    days = series.get("d")
    months = series.get("m")
    if period == "today" and days and len(days) == 24:
        return total(days[12:])
    if period == "yesterday" and days and len(days) == 24:
        return total(days[:12])
    if period == "month" and months and len(months) == 24:
        value = months[12 + now.month - 1]
        return float(value) if value is not None else 0.0
    if period == "year" and months and len(months) == 24:
        return total(months[12:])
    return None
