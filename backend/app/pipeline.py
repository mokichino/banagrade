from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class Pipeline(Protocol):
    async def status(self) -> dict[str, Any]: ...

    async def start(self, publish: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...

    async def stop(self) -> None: ...


class UnavailablePipeline:
    async def status(self) -> dict[str, Any]:
        return {"available": False, "state": "unavailable", "reason": "Pipeline adapter not configured"}

    async def start(self, publish: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        return None

    async def stop(self) -> None:
        return None