from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Iterable


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
    # These fields were added after the original public sample contract.  Keep
    # defaults so small scripts and tests that construct samples positionally
    # remain valid.
    sensor_provider: str = "LibreHardwareMonitor"
    sensor_available: bool = False
    sensor_message: str = ""
    disk_capacity_path: str = ""
    disk_io_scope: str = "all disks"

    @property
    def sensor_health(self) -> "SensorHealth":
        """Return the structured sensor state used by the presentation layer."""

        return SensorHealth(
            provider=self.sensor_provider,
            available=self.sensor_available,
            message=self.sensor_message or self.sensor_status,
        )

    @property
    def temperature_provider(self) -> str:
        return self.sensor_provider

    @property
    def temperature_available(self) -> bool:
        return self.sensor_available

    @property
    def disk_capacity_scope(self) -> str:
        return self.disk_capacity_path

    @property
    def disk_path(self) -> str:
        return self.disk_capacity_path

    @property
    def capacity_path(self) -> str:
        return self.disk_capacity_path


@dataclass(frozen=True)
class SensorHealth:
    """Typed temperature-provider state.

    ``message`` is deliberately kept as diagnostic text, while callers should
    use ``available`` and ``provider`` for branching.  This prevents UI code
    from coupling behavior to English error strings.
    """

    provider: str = "LibreHardwareMonitor"
    available: bool = False
    message: str = ""


class SampleHistory:
    def __init__(self, retention_seconds: float) -> None:
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be positive")
        self._retention_seconds = float(retention_seconds)
        self._items: list[HardwareSample] = []
        self._latest_timestamp: float | None = None

    def append(self, sample: HardwareSample) -> None:
        if not math.isfinite(float(sample.timestamp)):
            raise ValueError("sample.timestamp must be finite")
        if (
            self._latest_timestamp is not None
            and sample.timestamp < self._latest_timestamp - self._retention_seconds
        ):
            self._items.clear()
            self._latest_timestamp = None
        timestamps = [item.timestamp for item in self._items]
        index = bisect.bisect_right(timestamps, sample.timestamp)
        self._items.insert(index, sample)
        if self._latest_timestamp is None or sample.timestamp > self._latest_timestamp:
            self._latest_timestamp = sample.timestamp
        self._trim(self._latest_timestamp)

    @property
    def latest_timestamp(self) -> float | None:
        return self._latest_timestamp

    def as_tuple(self) -> tuple[HardwareSample, ...]:
        return tuple(self._items)

    def _trim(self, now: float) -> None:
        cutoff = now - self._retention_seconds
        first_valid = 0
        while first_valid < len(self._items) and self._items[first_valid].timestamp < cutoff:
            first_valid += 1
        if first_valid:
            del self._items[:first_valid]

    def __iter__(self) -> Iterable[HardwareSample]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)
