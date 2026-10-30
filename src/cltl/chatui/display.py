from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class DisplayEntry:
    sequence: int
    url: str
    name: str

    def to_dict(self) -> dict:
        return {"sequence": self.sequence, "url": self.url, "name": self.name}


class DisplayLog:
    """The pages shown in one scenario, oldest first, newest being the one on view.

    Only http(s) urls on an allowed host get in: the browser loads whatever is
    here into a frame, so this is the one place that decides what may be shown.
    `localhost` is always allowed, anything else has to be listed. Showing a url
    that is already in the log moves it to the end instead of adding a second
    row, so the history lists every page once.
    """

    def __init__(self, capacity: int = 50, allowed_hosts: Iterable[str] = ()):
        self._entries = deque(maxlen=capacity)
        self._allowed = LOCAL_HOSTS | {host.strip().lower() for host in allowed_hosts if host and host.strip()}
        self._next = 0
        self._lock = Lock()

    def is_allowed(self, url: str) -> bool:
        try:
            parts = urlsplit(url.strip())
            host = parts.hostname
            # `.port` raises on a malformed port
            parts.port
        except ValueError:
            return False

        # `username` is the tell for http://localhost@evil.example, where the
        # text that looks like the host is only the credentials.
        return (parts.scheme in ("http", "https") and host is not None
                and parts.username is None and parts.password is None
                and host.lower() in self._allowed)

    def add(self, url: str, name: str) -> Optional[DisplayEntry]:
        """The new entry, or None if the url may not be shown."""
        url = url.strip()
        if not self.is_allowed(url):
            return None

        with self._lock:
            for entry in [entry for entry in self._entries if entry.url == url]:
                self._entries.remove(entry)

            entry = DisplayEntry(self._next, url, name.strip())
            self._next += 1
            self._entries.append(entry)

            return entry

    def clear(self) -> None:
        """Forget the history. Sequence numbers keep counting, so a poller's
        `from` never points past events it has not seen."""
        with self._lock:
            self._entries.clear()

    def since(self, sequence: int = 0) -> List[DisplayEntry]:
        with self._lock:
            return [entry for entry in self._entries if entry.sequence >= sequence]

    @property
    def entries(self) -> List[DisplayEntry]:
        with self._lock:
            return list(self._entries)

    @property
    def last_sequence(self) -> int:
        with self._lock:
            return self._next - 1

    def latest(self) -> Optional[DisplayEntry]:
        with self._lock:
            return self._entries[-1] if self._entries else None
