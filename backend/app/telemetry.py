"""Edge-device telemetry (thesis Sections 3.6.1 and 4.7).

Every reading comes from the device; a value is ``None`` when the source is
unavailable (for example on a development laptop). Nothing is estimated.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

LATENCY_TARGET_MS = 2000.0


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def cpu_temperature_c() -> float | None:
    raw = _read("/sys/class/thermal/thermal_zone0/temp")
    try:
        return round(int(raw) / 1000, 1) if raw is not None else None
    except ValueError:
        return None


def fan_state() -> dict[str, Any] | None:
    current, maximum = _read("/sys/class/thermal/cooling_device0/cur_state"), _read("/sys/class/thermal/cooling_device0/max_state")
    if current is None:
        return None
    try:
        level, top = int(current), int(maximum) if maximum else None
    except ValueError:
        return None
    return {"level": level, "max_level": top, "active": level > 0}


def system_uptime_s() -> float | None:
    raw = _read("/proc/uptime")
    try:
        return float(raw.split()[0]) if raw else None
    except (ValueError, IndexError):
        return None


def device_model() -> str | None:
    raw = _read("/proc/device-tree/model")
    return raw.rstrip("\x00") if raw else None


def read_telemetry(service_started_at: float, storage: Any) -> dict[str, Any]:
    latency = storage.latency_stats(50)
    return {
        "device_model": device_model(),
        "service_uptime_s": round(time.time() - service_started_at, 1),
        "system_uptime_s": system_uptime_s(),
        "cpu_temperature_c": cpu_temperature_c(),
        "fan": fan_state(),
        "average_latency_ms": latency,
        "latency_target_ms": LATENCY_TARGET_MS,
        "latency_within_target": latency <= LATENCY_TARGET_MS if latency is not None else None,
        "database_connected": storage.ping(),
        "database": storage.path.name,
    }
