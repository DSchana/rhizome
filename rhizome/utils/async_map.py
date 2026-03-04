"""Thread-safe async dictionary for concurrent access."""

import asyncio
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class AsyncMap(Generic[K, V]):
    """A dictionary guarded by an ``asyncio.Lock`` for safe concurrent access.

    All mutating operations acquire the lock.  Read-only ``__contains__``
    and ``__len__`` do *not* acquire the lock since ``dict`` access is
    atomic in CPython and these are used in non-critical paths.
    """

    def __init__(self) -> None:
        self._data: dict[K, V] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: K, default: V | None = None) -> V | None:
        async with self._lock:
            return self._data.get(key, default)

    async def set(self, key: K, value: V) -> None:
        async with self._lock:
            self._data[key] = value

    async def pop(self, key: K, default: V | None = None) -> V | None:
        async with self._lock:
            return self._data.pop(key, default)

    def __contains__(self, key: K) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def keys(self):
        return self._data.keys()
