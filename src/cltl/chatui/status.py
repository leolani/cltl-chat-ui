import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Callable, List, Optional

_RANK = {"info": 0, "warning": 1, "error": 2}


@dataclass(frozen=True)
class StatusEntry:
    sequence: int
    time: float
    message: str
    source: str
    level: str
    progress: Optional[float]
    key: Optional[str]
    resolved: bool
    persistent: bool
    expires: Optional[float]

    def to_dict(self) -> dict:
        return {"sequence": self.sequence, "time": self.time, "message": self.message,
                "source": self.source, "level": self.level, "progress": self.progress,
                "key": self.key, "resolved": self.resolved,
                "persistent": self.persistent}


class StatusLog:
    """The timeline of one scenario's status events, and which of them still count.

    Every event is a row. Which row the bar shows is decided separately: among
    entries that are neither expired nor ended nor replaced, the highest level
    wins and the newest of those. A persistent entry is a line in the chat
    history, so it is a row here and never a candidate for the bar, nor does its
    key replace or end anything. Expiry is measured from receipt, because the
    emitter's clock is not ours.
    """

    def __init__(self, capacity: int = 200, clock: Callable[[], float] = time.time):
        self._entries = deque(maxlen=capacity)
        self._clock = clock
        self._next = 0
        self._lock = Lock()

    def add(self, message: str, source: str, level: str = "info", progress: Optional[float] = None,
            ttl: Optional[float] = None, key: Optional[str] = None, resolved: bool = False,
            persistent: bool = False) -> StatusEntry:
        with self._lock:
            now = self._clock()
            entry = StatusEntry(self._next, now, message, source, level, progress, key, resolved,
                                persistent, now + ttl if ttl is not None else None)
            self._next += 1
            self._entries.append(entry)

            return entry

    def clear(self) -> None:
        """Forget the timeline. Sequence numbers keep counting, so a poller's
        `from` never points past events it has not seen."""
        with self._lock:
            self._entries.clear()

    def since(self, sequence: int = 0) -> List[StatusEntry]:
        with self._lock:
            return [entry for entry in self._entries if entry.sequence >= sequence]

    @property
    def last_sequence(self) -> int:
        with self._lock:
            return self._next - 1

    def current(self) -> Optional[StatusEntry]:
        with self._lock:
            now = self._clock()
            superseded = set()
            candidates = []
            for entry in reversed(self._entries):
                if entry.persistent:
                    continue
                if entry.key:
                    if entry.key in superseded:
                        continue
                    superseded.add(entry.key)
                if entry.resolved:
                    continue
                if entry.expires is not None and entry.expires <= now:
                    continue
                candidates.append(entry)

            # candidates are newest first and max keeps the first of equals
            return max(candidates, key=lambda e: _RANK[e.level], default=None)
