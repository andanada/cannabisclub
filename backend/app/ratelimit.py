"""Límit simple de peticions per clau (p. ex. IP) amb finestra lliscant, en memòria del procés.
Limitació: cada procés té el seu comptador (amb diversos workers el límit efectiu es multiplica) i es perd en reiniciar;
és una primera barrera davant de ràfegues, el bloqueig per usuari de la base de dades és la definitiva."""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_hits: int, window_s: float, max_keys: int = 10_000):
        self.max_hits, self.window_s, self.max_keys = max_hits, window_s, max_keys
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > self.max_keys:  # evita que IPs falsejades facin créixer la memòria sense fi
                for k in [k for k, d in self._hits.items() if not d or d[-1] < now - self.window_s]:
                    del self._hits[k]
            d = self._hits[key]
            while d and d[0] <= now - self.window_s:
                d.popleft()
            if len(d) >= self.max_hits:
                return False
            d.append(now)
            return True
