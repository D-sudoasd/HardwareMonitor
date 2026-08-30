from __future__ import annotations

import math
import os

from collectors.temperature import TemperatureCollector


def test_cpu_temperature_prefers_package_sensor() -> None:
    values = [
        ("CPU Core #1", 50.0),
        ("CPU Package", 61.5),
        ("CPU Core #2", 54.0),
    ]

    assert TemperatureCollector._choose_cpu_temperature(values) == 61.5


def test_cpu_temperature_falls_back_to_max_core_sensor() -> None:
    values = [
        ("CPU Core #1", 50.0),
        ("CPU Core #2", 54.0),
    ]

    assert TemperatureCollector._choose_cpu_temperature(values) == 54.0


def test_missing_temperatures_return_none() -> None:
    assert TemperatureCollector._choose_cpu_temperature([]) is None
    assert TemperatureCollector._choose_max_temperature([]) is None


def test_temperature_value_rejects_invalid_sensor_values() -> None:
    collector = TemperatureCollector(dll_path="missing.dll")

    class Sensor:
        SensorType = "Temperature"
        Value = 0.0

    assert collector._temperature_value(Sensor()) is None


def test_temperature_value_rejects_non_finite_sensor_values() -> None:
    collector = TemperatureCollector(dll_path="missing.dll")

    assert collector._valid_temperature_value(math.nan) is None
    assert collector._valid_temperature_value(math.inf) is None
    assert collector._valid_temperature_value(-math.inf) is None
    assert collector._choose_cpu_temperature([("CPU Package", math.nan)]) is None
    assert collector._choose_max_temperature([("disk", math.inf)]) is None


def test_temperature_collector_retains_and_closes_dll_directory_handle(monkeypatch, tmp_path) -> None:
    class Handle:
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    handle = Handle()
    monkeypatch.setattr(os, "add_dll_directory", lambda path: handle, raising=False)
    collector = TemperatureCollector(dll_path=tmp_path / "missing.dll")

    collector._prepare_assembly_path()
    assert collector._dll_directory_handle is handle

    collector.close()
    collector.close()
    assert handle.close_count == 1


def test_temperature_collector_closes_lhm_computer_once() -> None:
    collector = TemperatureCollector(dll_path="missing.dll")

    class Computer:
        def __init__(self) -> None:
            self.close_count = 0

        def Close(self) -> None:
            self.close_count += 1

    computer = Computer()
    collector._computer = computer
    collector.close()
    collector.close()

    assert computer.close_count == 1


def test_collect_reads_nested_cpu_temperature_sensor() -> None:
    collector = TemperatureCollector(dll_path="missing.dll")
    collector._computer = FakeComputer(
        [
            FakeHardware(
                hardware_type="Motherboard",
                name="Board",
                sensors=[],
                sub_hardware=[
                    FakeHardware(
                        hardware_type="Cpu",
                        name="Processor",
                        sensors=[FakeSensor("Core (Tctl/Tdie)", 58.5)],
                    )
                ],
            )
        ]
    )

    snapshot = collector.collect()

    assert snapshot.cpu_temp_c == 58.5


def test_collect_reports_invalid_cpu_sensor_values() -> None:
    collector = TemperatureCollector(dll_path="missing.dll")
    collector._computer = FakeComputer(
        [
            FakeHardware(
                hardware_type="Cpu",
                name="Processor",
                sensors=[FakeSensor("Core (Tctl/Tdie)", 0.0)],
            )
        ]
    )

    snapshot = collector.collect()

    assert snapshot.cpu_temp_c is None
    assert "invalid" in snapshot.status.message


def test_collect_keeps_valid_child_when_parent_update_fails() -> None:
    collector = TemperatureCollector(dll_path="missing.dll")
    collector._computer = FakeComputer(
        [
            FakeHardware(
                hardware_type="Motherboard",
                name="Board",
                sensors=[],
                sub_hardware=[
                    FakeHardware(
                        hardware_type="Cpu",
                        name="Processor",
                        sensors=[FakeSensor("Core (Tctl/Tdie)", 58.5)],
                    )
                ],
                update_error=OSError("parent update failed"),
            )
        ]
    )

    snapshot = collector.collect()

    assert snapshot.cpu_temp_c == 58.5
    assert snapshot.status.available is False
    assert "hardware node update failed" in snapshot.status.message


class FakeSensor:
    SensorType = "Temperature"

    def __init__(self, name: str, value: float) -> None:
        self.Name = name
        self.Value = value


class FakeHardware:
    def __init__(
        self,
        hardware_type: str,
        name: str,
        sensors: list[FakeSensor],
        sub_hardware: list["FakeHardware"] | None = None,
        update_error: Exception | None = None,
    ) -> None:
        self.HardwareType = hardware_type
        self.Name = name
        self.Sensors = sensors
        self.SubHardware = sub_hardware or []
        self.update_error = update_error

    def Update(self) -> None:
        if self.update_error is not None:
            raise self.update_error
        return None


class FakeComputer:
    def __init__(self, hardware: list[FakeHardware]) -> None:
        self.Hardware = hardware
