"""Physical LED check: steps through every LED state on the real GPIO pins.

Stop the backend first (it holds the pins), then run from backend/:
    ../.venv/bin/python scripts/test_leds.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["BANAGRADE_ENABLE_GPIO"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "/usr/lib/python3/dist-packages" not in sys.path:
    sys.path.append("/usr/lib/python3/dist-packages")  # apt gpiozero/lgpio, same as the backend

from app.leds import LedController, LedState  # noqa: E402

STEPS = [
    (LedState.READY, "green steady", 2),
    (LedState.CAPTURE, "all LEDs flash (snapshot)", 1),
    (LedState.CLASS_A, "yellow = Class A", 2),
    (LedState.CLASS_B, "blue = Class B", 2),
    (LedState.REJECTED, "red = Rejected", 2),
    (LedState.BOOTING, "red slow blink = booting", 4),
    (LedState.ERROR, "red fast blink = error", 4),
    (LedState.READY, "back to green", 2),
]


def main() -> int:
    leds = LedController()
    leds.open()
    if not leds.hardware_available:
        print(f"GPIO not available: {leds.error}")
        return 1
    print(f"Pins (BCM): {leds.pins}")
    try:
        for state, label, seconds in STEPS:
            print(f"{state.value:9} {label}", flush=True)
            leds.set(state)
            time.sleep(seconds)
    finally:
        leds.close()
    print("Done, all LEDs off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
