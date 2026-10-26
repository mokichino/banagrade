"""Physical GPIO LED indicators (thesis Sections 3.6.5 and 4.8.2).

Green = system ready, Yellow = Class A, Blue = Class B, Red = Rejected.
Slow red blink = booting / calibrating; fast red blink = hardware error,
camera obstructed or inadequate lighting. A short white-out burst of all
LEDs confirms a snapshot. The current state is also published to the web
dashboard so the digital indicator mirrors the sorting floor.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from enum import StrEnum
from typing import Any


class LedState(StrEnum):
    BOOTING = "booting"
    READY = "ready"
    CAPTURE = "capture"
    CLASS_A = "class_a"
    CLASS_B = "class_b"
    REJECTED = "rejected"
    ERROR = "error"
    # A scan that could not be graded (unsure Stage 1, no measurable outline, not a bunch). The floor sees the same
    # fast red blink as ERROR (thesis 3.6.5); only the dashboard tells them apart, so this is not shown as a fault.
    CHECK = "check"


GRADE_TO_LED = {"Class A": LedState.CLASS_A, "Class B": LedState.CLASS_B, "Rejected": LedState.REJECTED}

DEFAULT_PINS = {"green": 17, "yellow": 27, "blue": 22, "red": 23}


class LedController:
    def __init__(self, on_change: Callable[[LedState], None] | None = None, outputs: dict[str, Any] | None = None) -> None:
        self.state = LedState.BOOTING
        self.hardware_available = outputs is not None
        self.error: str | None = None
        self._outputs: dict[str, Any] = outputs or {}
        self._on_change = on_change
        self._lock = threading.Lock()
        # Physical LEDs are opt-in until they are wired (BANAGRADE_ENABLE_GPIO=true).
        # The state machine still runs so the dashboard indicator works without hardware.
        self.gpio_enabled = outputs is not None or os.getenv("BANAGRADE_ENABLE_GPIO", "false").lower() == "true"

    @property
    def pins(self) -> dict[str, int]:
        return {color: int(os.getenv(f"BANAGRADE_LED_{color.upper()}", str(pin))) for color, pin in DEFAULT_PINS.items()}

    def open(self) -> None:
        if self._outputs:
            return
        if not self.gpio_enabled:
            self.error = None
            return
        try:
            from gpiozero import LED
        except ImportError:
            self.error = "gpiozero is not installed; physical LEDs are disabled"
            return
        try:
            self._outputs = {color: LED(pin) for color, pin in self.pins.items()}
            self.hardware_available = True
        except Exception as error:  # gpiozero raises several backend-specific errors
            self.error = f"GPIO unavailable: {error}"
            self._outputs = {}
        self._apply(self.state)

    def close(self) -> None:
        for output in self._outputs.values():
            try:
                output.off()
                output.close()
            except Exception:
                pass
        self._outputs = {}
        self.hardware_available = False

    def set(self, state: LedState) -> None:
        with self._lock:
            changed = state is not self.state
            self.state = state
            self._apply(state)
        if changed and self._on_change:
            self._on_change(state)

    def show_grade(self, grade: str | None) -> None:
        self.set(GRADE_TO_LED.get(grade or "", LedState.ERROR))

    def _apply(self, state: LedState) -> None:
        if not self._outputs:
            return
        for output in self._outputs.values():
            output.off()
        out = self._outputs
        if state is LedState.READY:
            out["green"].on()
        elif state is LedState.CLASS_A:
            out["yellow"].on()
        elif state is LedState.CLASS_B:
            out["blue"].on()
        elif state is LedState.REJECTED:
            out["red"].on()
        elif state is LedState.BOOTING:
            out["red"].blink(on_time=0.8, off_time=0.8)
        elif state in (LedState.ERROR, LedState.CHECK):
            out["red"].blink(on_time=0.12, off_time=0.12)
        elif state is LedState.CAPTURE:
            for output in out.values():
                output.blink(on_time=0.08, off_time=0.08, n=2)

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "mode": "physical" if self.hardware_available else ("unavailable" if self.gpio_enabled else "software"),
            "gpio_enabled": self.gpio_enabled,
            "hardware_available": self.hardware_available,
            "pins": self.pins,
            "error": self.error,
        }
