"""Staging-only Raspberry Pi 5 bridge.

The bridge is intentionally disabled until GPIO/camera wiring is validated.
Set ENABLE_PI_HARDWARE to True and provide a transport implementation before use.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

ENABLE_PI_HARDWARE = os.getenv("ENABLE_PI_HARDWARE", "false").lower() == "true"


class RaspberryPiBridge:
    def __init__(self) -> None:
        self.enabled = ENABLE_PI_HARDWARE

    async def telemetry(self) -> AsyncIterator[dict]:
        if not self.enabled:
            return
        # Reserved for an authenticated serial/WebSocket transport on the Pi 5.
        # No GPIO, camera, or serial device is opened while staging is disabled.
        yield {"type": "status", "source": "raspberry-pi-5", "status": "connected"}

    async def close(self) -> None:
        return None


hardware_bridge = RaspberryPiBridge()
