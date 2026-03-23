"""Pipeline progress tracking with SSE event queue."""

import asyncio
import json
import time
from dataclasses import dataclass, field


@dataclass
class ProgressEvent:
    event: str
    data: dict
    timestamp: float = field(default_factory=time.time)


class ProgressTracker:
    """Thread-safe progress tracker that feeds an asyncio queue for SSE streaming."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._history: list[ProgressEvent] = []
        self.current_phase: str = "idle"
        self.start_time: float = time.time()

    def emit(self, event: str, data: dict):
        pe = ProgressEvent(event=event, data=data)
        self._history.append(pe)
        if event.startswith("phase"):
            self.current_phase = data.get("phase", self.current_phase)
        try:
            self._queue.put_nowait(pe)
        except asyncio.QueueFull:
            pass

    async def next_event(self, timeout: float = 1.0) -> ProgressEvent | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def get_history(self) -> list[dict]:
        return [
            {"event": pe.event, "data": pe.data, "timestamp": pe.timestamp}
            for pe in self._history
        ]

    def summary(self) -> dict:
        return {
            "current_phase": self.current_phase,
            "elapsed_seconds": round(time.time() - self.start_time, 1),
            "event_count": len(self._history),
        }
