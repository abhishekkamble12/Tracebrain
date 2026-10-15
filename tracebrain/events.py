"""In-process event bus: orchestrator events -> any number of live subscribers (SSE streams).

Each investigation keeps a history, so a client that connects late (or reconnects) first gets
everything that already happened, then live events, ending after `done`.
Publish and subscribe must run on the same event loop (the API's).
"""

import asyncio
import time
from collections import defaultdict
from typing import AsyncIterator

END_KINDS = {"done"}


class EventBus:
    def __init__(self, history_limit: int = 5000):
        self._history: dict[str, list[dict]] = defaultdict(list)
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._limit = history_limit

    def publish(self, inv_id: str, kind: str, data: dict) -> dict:
        history = self._history[inv_id]
        event = {"seq": len(history) + 1, "kind": kind, "ts": time.time(), "data": data}
        if len(history) < self._limit:
            history.append(event)
        for q in list(self._subscribers[inv_id]):
            q.put_nowait(event)
        return event

    def history(self, inv_id: str) -> list[dict]:
        return list(self._history.get(inv_id, []))

    async def subscribe(self, inv_id: str, after_seq: int = 0) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[inv_id].add(q)  # register before reading history so nothing is missed
        try:
            last = after_seq
            snapshot = self.history(inv_id)
            for i, event in enumerate(snapshot):
                if event["seq"] > last:
                    last = event["seq"]
                    yield event
                    # An earlier `done` (before a resume) doesn't end the stream; only the latest does.
                    if event["kind"] in END_KINDS and i == len(snapshot) - 1:
                        return
            while True:
                event = await q.get()
                if event["seq"] <= last:
                    continue
                last = event["seq"]
                yield event
                if event["kind"] in END_KINDS:
                    return
        finally:
            self._subscribers[inv_id].discard(q)
