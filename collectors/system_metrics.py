from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

try:
    import psutil
except ModuleNotFoundError:  # pragma: no cover - exercised by runtime startup.
    psutil = None  # type: ignore[assignment]


BYTES_PER_MIB = 1024 * 1024
BYTES_PER_GIB = 1024 * 1024 * 1024


@dataclass(frozen=True)
class SystemMetrics:
    cpu_percent: float
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    disk_usage_percent: float
    disk_read_mb_s: float
    disk_write_mb_s: float
    disk_active_percent: float


def default_disk_path() -> str:
    if os.name == "nt":
        return f"{os.environ.get('SystemDrive', 'C:')}\\"
    return "/"


def compute_disk_io_rates(
    previous: Any | None,
    current: Any | None,
    elapsed_seconds: float,
) -> tuple[float, float, float]:
    if previous is None or current is None or elapsed_seconds <= 0:
        return 0.0, 0.0, 0.0

    read_delta = max(0, int(current.read_bytes) - int(previous.read_bytes))
    write_delta = max(0, int(current.write_bytes) - int(previous.write_bytes))
    read_mb_s = read_delta / BYTES_PER_MIB / elapsed_seconds
    write_mb_s = write_delta / BYTES_PER_MIB / elapsed_seconds

    active_percent = 0.0
    previous_busy = getattr(previous, "busy_time", None)
    current_busy = getattr(current, "busy_time", None)
    if previous_busy is not None and current_busy is not None:
        busy_delta_seconds = max(0.0, (float(current_busy) - float(previous_busy)) / 1000.0)
        active_percent = min(100.0, busy_delta_seconds / elapsed_seconds * 100.0)

    return read_mb_s, write_mb_s, active_percent


class SystemMetricsCollector:
    def __init__(
        self,
        disk_path: str | None = None,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        if psutil is None:
            raise RuntimeError(
                "psutil is required. Install dependencies with: python -m pip install -r requirements.txt"
            )

        self._disk_path = disk_path or default_disk_path()
        self._time_source = time_source
        self._last_disk_counters: Any | None = None
        self._last_disk_time: float | None = None
        psutil.cpu_percent(interval=None)

    def collect(self) -> SystemMetrics:
        now = self._time_source()
        cpu_percent = float(psutil.cpu_percent(interval=None))
        memory = psutil.virtual_memory()
        disk_usage = psutil.disk_usage(self._disk_path)
        disk_counters = psutil.disk_io_counters()

        elapsed = 0.0 if self._last_disk_time is None else now - self._last_disk_time
        disk_read_mb_s, disk_write_mb_s, disk_active_percent = compute_disk_io_rates(
            self._last_disk_counters,
            disk_counters,
            elapsed,
        )

        self._last_disk_counters = disk_counters
        self._last_disk_time = now

        return SystemMetrics(
            cpu_percent=cpu_percent,
            memory_percent=float(memory.percent),
            memory_used_gb=float(memory.used) / BYTES_PER_GIB,
            memory_total_gb=float(memory.total) / BYTES_PER_GIB,
            disk_usage_percent=float(disk_usage.percent),
            disk_read_mb_s=disk_read_mb_s,
            disk_write_mb_s=disk_write_mb_s,
            disk_active_percent=disk_active_percent,
        )
