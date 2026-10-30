"""Keeping the Pi's clock right without an RTC battery.

With no battery the Pi 5's RTC forgets the time when the power is cut. If there is no internet when power comes back,
the clock starts again from about when it last saved the time, hours or days behind, and scans get the wrong date and
shift. Two things put it right: internet time (systemd-timesyncd) once a network with data is up, or the time of a
phone that opens the dashboard, which phones keep from the cell network even without mobile data.

Either way the clock jumps forward. ClockWatch notices the jump, and Storage.correct_clock moves everything recorded
since boot by the same amount, since all of it was behind by exactly that much.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

# Smaller steps are NTP's ordinary corrections, not a clock that came back wrong; this must also exceed WATCH_S.
MIN_JUMP_S = 120.0
WATCH_S = 15.0


def boot_id() -> str | None:
    """Changes on every boot, so records made since this boot can be told apart from earlier ones."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def time_synchronized() -> bool | None:
    """True once systemd-timesyncd has set the clock from internet time since boot; None where it does not run."""
    folder = Path("/run/systemd/timesync")
    return (folder / "synchronized").exists() if folder.is_dir() else None


def set_clock(epoch_s: float) -> None:
    """Needs CAP_SYS_TIME, which deploy/banagrade.service grants; PermissionError without it."""
    time.clock_settime(time.CLOCK_REALTIME, epoch_s)


class ClockWatch:
    """Notices the wall clock jumping forward against the monotonic clock, which counts steadily since boot."""

    def __init__(self) -> None:
        self.offset = time.time() - time.monotonic()

    def check(self) -> tuple[float, datetime] | None:
        """(jump in seconds, cutoff) after a forward jump of at least MIN_JUMP_S, else None.

        Everything recorded before the jump is stamped at or before the cutoff, and everything after it later, as long
        as the jump is bigger than the time since the previous check. A backward step is left alone: Storage keeps the
        current shift rather than going back a day (see clock_trusted).
        """
        wall, monotonic = time.time(), time.monotonic()
        jump, self.offset = wall - monotonic - self.offset, wall - monotonic
        if jump < MIN_JUMP_S:
            return None
        return jump, datetime.fromtimestamp(wall - jump, UTC)
