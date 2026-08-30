from __future__ import annotations

import math
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


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


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
    # Disk capacity is measured for this configured path (normally C:), while
    # psutil's disk I/O counters are intentionally aggregate across devices.
    disk_capacity_path: str = ""
    disk_io_scope: str = "all disks"

    @property
    def disk_capacity_scope(self) -> str:
        return self.disk_capacity_path

    @property
    def disk_path(self) -> str:
        return self.disk_capacity_path

    @property
    def capacity_path(self) -> str:
        return self.disk_capacity_path

    @property
    def io_scope(self) -> str:
        return self.disk_io_scope


def default_disk_path() -> str:
    if os.name == "nt":
        return f"{os.environ.get('SystemDrive', 'C:')}\\"
    return "/"


def compute_disk_io_rates(
    previous: Any | None,
    current: Any | None,
    elapsed_seconds: float,
) -> tuple[float, float, float]:
    elapsed = _finite_float(elapsed_seconds)
    if previous is None or current is None or elapsed is None or elapsed <= 0:
        return 0.0, 0.0, 0.0

    previous_read = _finite_float(getattr(previous, "read_bytes", None))
    current_read = _finite_float(getattr(current, "read_bytes", None))
    previous_write = _finite_float(getattr(previous, "write_bytes", None))
    current_write = _finite_float(getattr(current, "write_bytes", None))
    read_delta = 0.0 if previous_read is None or current_read is None else max(0.0, current_read - previous_read)
    write_delta = 0.0 if previous_write is None or current_write is None else max(0.0, current_write - previous_write)
    read_mb_s = read_delta / BYTES_PER_MIB / elapsed
    write_mb_s = write_delta / BYTES_PER_MIB / elapsed

    active_percent = 0.0
    previous_busy = getattr(previous, "busy_time", None)
    current_busy = getattr(current, "busy_time", None)
    previous_busy_value = _finite_float(previous_busy)
    current_busy_value = _finite_float(current_busy)
    if previous_busy_value is not None and current_busy_value is not None:
        busy_delta_seconds = max(0.0, (current_busy_value - previous_busy_value) / 1000.0)
        active_percent = min(100.0, busy_delta_seconds / elapsed * 100.0)

    if not all(math.isfinite(value) for value in (read_mb_s, write_mb_s, active_percent)):
        return 0.0, 0.0, 0.0

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

    @property
    def disk_capacity_path(self) -> str:
        return self._disk_path

    @property
    def disk_io_scope(self) -> str:
        return "all disks"

    def collect(self) -> SystemMetrics:
        now = _finite_float(self._time_source())
        cpu_percent = _finite_float(psutil.cpu_percent(interval=None))
        memory = psutil.virtual_memory()
        disk_usage = psutil.disk_usage(self._disk_path)
        disk_counters = psutil.disk_io_counters()

        elapsed = 0.0 if now is None or self._last_disk_time is None else now - self._last_disk_time
        disk_read_mb_s, disk_write_mb_s, disk_active_percent = compute_disk_io_rates(
            self._last_disk_counters,
            disk_counters,
            elapsed,
        )

        self._last_disk_counters = disk_counters
        if now is not None:
            self._last_disk_time = now

        cpu_value = _finite_float(cpu_percent)
        memory_percent = _finite_float(memory.percent)
        memory_used = _finite_float(memory.used)
        memory_total = _finite_float(memory.total)
        disk_percent = _finite_float(disk_usage.percent)
        if any(value is None for value in (cpu_value, memory_percent, memory_used, memory_total, disk_percent)):
            raise ValueError("psutil returned a non-finite system metric")

        return SystemMetrics(
            cpu_percent=cpu_value,
            memory_percent=memory_percent,
            memory_used_gb=memory_used / BYTES_PER_GIB,
            memory_total_gb=memory_total / BYTES_PER_GIB,
            disk_usage_percent=disk_percent,
            disk_read_mb_s=disk_read_mb_s,
            disk_write_mb_s=disk_write_mb_s,
            disk_active_percent=disk_active_percent,
            disk_capacity_path=self._disk_path,
            disk_io_scope=self.disk_io_scope,
        )

    def close(self) -> None:
        """Keep the worker shutdown contract uniform across collectors."""

        # psutil does not own a long-lived native handle here.  The method is
        # intentionally idempotent so a worker can close optional collectors
        # without special-casing this one.
        return None
