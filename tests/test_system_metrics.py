from __future__ import annotations

import math
from types import SimpleNamespace

from collectors.system_metrics import BYTES_PER_MIB, compute_disk_io_rates


def test_disk_io_rates_are_zero_for_first_sample() -> None:
    current = SimpleNamespace(read_bytes=10 * BYTES_PER_MIB, write_bytes=5 * BYTES_PER_MIB, busy_time=2000)

    read_rate, write_rate, active = compute_disk_io_rates(None, current, 1.0)

    assert read_rate == 0.0
    assert write_rate == 0.0
    assert active == 0.0


def test_disk_io_rates_use_counter_deltas() -> None:
    previous = SimpleNamespace(read_bytes=1 * BYTES_PER_MIB, write_bytes=2 * BYTES_PER_MIB, busy_time=1000)
    current = SimpleNamespace(read_bytes=5 * BYTES_PER_MIB, write_bytes=8 * BYTES_PER_MIB, busy_time=1500)

    read_rate, write_rate, active = compute_disk_io_rates(previous, current, 2.0)

    assert read_rate == 2.0
    assert write_rate == 3.0
    assert active == 25.0


def test_disk_active_percent_is_clamped() -> None:
    previous = SimpleNamespace(read_bytes=0, write_bytes=0, busy_time=0)
    current = SimpleNamespace(read_bytes=0, write_bytes=0, busy_time=5000)

    _, _, active = compute_disk_io_rates(previous, current, 1.0)

    assert active == 100.0


def test_disk_io_rates_reject_non_finite_elapsed_and_counters() -> None:
    previous = SimpleNamespace(read_bytes=1 * BYTES_PER_MIB, write_bytes=2 * BYTES_PER_MIB, busy_time=1000)
    current = SimpleNamespace(read_bytes=math.nan, write_bytes=math.inf, busy_time=math.nan)

    assert compute_disk_io_rates(previous, current, math.nan) == (0.0, 0.0, 0.0)
    assert compute_disk_io_rates(previous, current, 1.0) == (0.0, 0.0, 0.0)


def test_disk_io_rates_are_finite_for_extreme_inputs() -> None:
    previous = SimpleNamespace(read_bytes=-1e308, write_bytes=-1e308, busy_time=-1e308)
    current = SimpleNamespace(read_bytes=1e308, write_bytes=1e308, busy_time=1e308)

    values = compute_disk_io_rates(previous, current, 1e-308)
    assert all(math.isfinite(value) for value in values)
    assert values == (0.0, 0.0, 0.0)
