"""Runtime configuration from environment variables (see deploy/onecta-modbus.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"ONECTA_{name}", default)


def _time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "/var/lib/onecta-modbus")))
    modbus_host: str = field(default_factory=lambda: _env("MODBUS_HOST", "0.0.0.0"))
    modbus_port: int = field(default_factory=lambda: int(_env("MODBUS_PORT", "502")))
    web_host: str = field(default_factory=lambda: _env("WEB_HOST", "0.0.0.0"))
    web_port: int = field(default_factory=lambda: int(_env("WEB_PORT", "8080")))
    web_password: str = field(default_factory=lambda: _env("WEB_PASSWORD", ""))
    # Daikin allows ~200 API calls per day per account. 10 min by day + 30 min at night
    # is about 120 polls, leaving room for commands.
    poll_day_minutes: float = field(default_factory=lambda: float(_env("POLL_DAY_MINUTES", "10")))
    poll_night_minutes: float = field(default_factory=lambda: float(_env("POLL_NIGHT_MINUTES", "30")))
    day_start: time = field(default_factory=lambda: _time(_env("DAY_START", "07:00")))
    night_start: time = field(default_factory=lambda: _time(_env("NIGHT_START", "22:00")))
    # Daikin can return stale values right after a command; confirm a bit later.
    refresh_after_write: float = field(default_factory=lambda: float(_env("REFRESH_AFTER_WRITE", "45")))
    write_debounce: float = field(default_factory=lambda: float(_env("WRITE_DEBOUNCE", "2")))
    low_budget: int = field(default_factory=lambda: int(_env("LOW_BUDGET", "40")))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
