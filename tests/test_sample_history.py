from __future__ import annotations

from models.sample import HardwareSample, SampleHistory


def make_sample(timestamp: float) -> HardwareSample:
    return HardwareSample(
        timestamp=timestamp,
        cpu_percent=0.0,
        memory_percent=0.0,
        memory_used_gb=0.0,
        memory_total_gb=0.0,
        disk_usage_percent=0.0,
        disk_read_mb_s=0.0,
        disk_write_mb_s=0.0,
        disk_active_percent=0.0,
        cpu_temp_c=None,
        disk_temp_c=None,
        sensor_status="Sensor unavailable",
    )


def test_history_keeps_only_retention_window() -> None:
    history = SampleHistory(retention_seconds=10.0)

    history.append(make_sample(100.0))
    history.append(make_sample(105.0))
    history.append(make_sample(111.0))

    assert [sample.timestamp for sample in history] == [105.0, 111.0]
