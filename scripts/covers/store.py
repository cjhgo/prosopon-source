"""JSON cache, negative-cache TTL, and per-source rate limiting."""

from __future__ import annotations

import json
import os
import time

from match import norm


def key_for(item: dict) -> str:
    return "|".join(
        [
            str(item.get("type", "")),
            norm(item.get("title")),
            norm(item.get("creator")),
        ]
    )


class Cache:
    def __init__(self, path: str, negative_ttl: int = 7 * 24 * 3600):
        self.path = path
        self.negative_ttl = negative_ttl
        self.data: dict = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except json.JSONDecodeError:
                self.data = {}

    def get(self, key: str) -> dict | None:
        entry = self.data.get(key)
        if not entry:
            return None
        if entry.get("status") == "miss":
            age = time.time() - float(entry.get("fetched_at", 0))
            if age > self.negative_ttl:
                return None
        return entry

    def set(self, key: str, entry: dict) -> None:
        entry = dict(entry)
        entry["fetched_at"] = time.time()
        entry.setdefault("fetched_at_iso", time.strftime("%Y-%m-%dT%H:%M:%S"))
        self.data[key] = entry
        self.save()

    def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.save()

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


class RateLimiter:
    """Minimum interval between calls to each source."""

    def __init__(self, intervals: dict[str, float]):
        self.intervals = intervals
        self.last: dict[str, float] = {}

    def wait(self, source: str) -> None:
        interval = self.intervals.get(source, 0.0)
        if interval <= 0:
            return
        elapsed = time.time() - self.last.get(source, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self.last[source] = time.time()
