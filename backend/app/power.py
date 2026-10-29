"""Reboot and shut down the Pi from the System Status page.

The service runs as the unprivileged banagrade user with NoNewPrivileges, so it cannot sudo. It asks
systemd-logind over D-Bus instead, which polkit allows for that user only once
deploy/50-banagrade-power.rules is installed. Without the rule logind answers "challenge" (it wants a
password), and the dashboard shows the buttons as unavailable.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

# action -> (logind permission check, systemctl verb)
ACTIONS = {"reboot": ("CanReboot", "reboot"), "shutdown": ("CanPowerOff", "poweroff")}
# Long enough for the HTTP response and the websocket event to reach the dashboard first.
DELAY_S = 1.5


async def _run(*args: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    return process.returncode or 0, (stdout or stderr).decode().strip()


async def permission(action: str) -> str:
    """logind's answer: "yes", "challenge" (needs a password, so not usable here), "no" or "na"."""
    method = ACTIONS[action][0]
    try:
        code, output = await _run("busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", method)
    except FileNotFoundError:  # not a systemd host
        return "na"
    # busctl prints the D-Bus reply as: s "yes"
    return output.split('"')[1] if code == 0 and output.count('"') >= 2 else "na"


async def status() -> dict[str, dict[str, object]]:
    answers = await asyncio.gather(*(permission(action) for action in ACTIONS))
    return {action: {"allowed": answer == "yes", "permission": answer} for action, answer in zip(ACTIONS, answers)}


async def execute(action: str) -> None:
    """Wait DELAY_S, then reboot or power off. -i skips inhibitor locks; the polkit rule allows that too."""
    await asyncio.sleep(DELAY_S)
    code, output = await _run("systemctl", ACTIONS[action][1], "-i")
    if code != 0:
        raise RuntimeError(output or f"systemctl {ACTIONS[action][1]} exited with {code}")
