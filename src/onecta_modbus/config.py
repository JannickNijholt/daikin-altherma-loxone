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
    # Poll at least this often, even when the budget is tight.
    max_poll_minutes: float = field(default_factory=lambda: float(_env("MAX_POLL_MINUTES", "60")))
    # Daily API calls polling leaves untouched, so Loxone commands keep working.
    command_reserve: int = field(default_factory=lambda: int(_env("COMMAND_RESERVE", "50")))
    # Guard against runaway Loxone logic.
    max_commands_per_hour: int = field(default_factory=lambda: int(_env("MAX_COMMANDS_PER_HOUR", "20")))
    # Stop sending commands when this few calls are left today.
    min_calls_left: int = field(default_factory=lambda: int(_env("MIN_CALLS_LEFT", "5")))
    # Extra poll this many seconds after a command to confirm it; 0 = rely on the next regular poll.
    refresh_after_write: float = field(default_factory=lambda: float(_env("REFRESH_AFTER_WRITE", "0")))
    write_debounce: float = field(default_factory=lambda: float(_env("WRITE_DEBOUNCE", "3")))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
