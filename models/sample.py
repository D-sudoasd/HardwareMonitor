from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable


@dataclass(frozen=True)
class HardwareSample:
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    disk_usage_percent: float
    disk_read_mb_s: float
    disk_write_mb_s: float
    disk_active_percent: float
    cpu_temp_c: float | None
    disk_temp_c: float | None
    sensor_status: str


class SampleHistory:
    def __init__(self, retention_seconds: float) -> None:
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be positive")
        self._retention_seconds = float(retention_seconds)
        self._items: Deque[HardwareSample] = deque()

    def append(self, sample: HardwareSample) -> None:
        self._items.append(sample)
        self._trim(sample.timestamp)

    def as_tuple(self) -> tuple[HardwareSample, ...]:
        return tuple(self._items)

    def _trim(self, now: float) -> None:
        cutoff = now - self._retention_seconds
        while self._items and self._items[0].timestamp < cutoff:
            self._items.popleft()

    def __iter__(self) -> Iterable[HardwareSample]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)
