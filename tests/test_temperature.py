from __future__ import annotations

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
    ) -> None:
        self.HardwareType = hardware_type
        self.Name = name
        self.Sensors = sensors
        self.SubHardware = sub_hardware or []

    def Update(self) -> None:
        return None


class FakeComputer:
    def __init__(self, hardware: list[FakeHardware]) -> None:
        self.Hardware = hardware
