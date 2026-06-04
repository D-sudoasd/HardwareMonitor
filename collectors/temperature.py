from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def application_base_path() -> Path:
    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        return Path(pyinstaller_root)
    return Path(__file__).resolve().parents[1]


def default_dll_path() -> Path:
    return application_base_path() / "vendor" / "LibreHardwareMonitorLib.dll"


@dataclass(frozen=True)
class SensorStatus:
    provider: str
    available: bool
    message: str


@dataclass(frozen=True)
class TemperatureSnapshot:
    cpu_temp_c: float | None
    disk_temp_c: float | None
    status: SensorStatus


class TemperatureCollector:
    def __init__(self, dll_path: str | Path | None = None) -> None:
        self._dll_path = Path(dll_path) if dll_path else default_dll_path()
        self._computer: Any | None = None
        self._sensor_type: Any | None = None
        self._status = SensorStatus(
            provider="LibreHardwareMonitor",
            available=False,
            message=f"LibreHardwareMonitorLib.dll not found: {self._dll_path}",
        )
        self._initialize()

    def collect(self) -> TemperatureSnapshot:
        if self._computer is None:
            return TemperatureSnapshot(None, None, self._status)

        cpu_values: list[tuple[str, float]] = []
        storage_values: list[tuple[str, float]] = []
        invalid_cpu_values = 0
        invalid_storage_values = 0

        try:
            for hardware in self._iter_hardware(self._computer.Hardware):
                hardware_type = str(hardware.HardwareType).lower()
                for sensor in hardware.Sensors:
                    raw_value = self._raw_temperature_value(sensor)
                    if raw_value is None:
                        continue
                    name = str(sensor.Name)
                    value = self._valid_temperature_value(raw_value)
                    sensor_target = self._classify_temperature_sensor(hardware_type, name)
                    if sensor_target == "cpu":
                        if value is None:
                            invalid_cpu_values += 1
                            continue
                        cpu_values.append((name, value))
                    elif sensor_target == "storage":
                        if value is None:
                            invalid_storage_values += 1
                            continue
                        storage_values.append((name, value))

            cpu_temp = self._choose_cpu_temperature(cpu_values)
            disk_temp = self._choose_max_temperature(storage_values)
            status = self._build_status(cpu_temp, disk_temp, invalid_cpu_values, invalid_storage_values)
            return TemperatureSnapshot(cpu_temp, disk_temp, status)
        except Exception as exc:  # Hardware sensor APIs can fail per machine/driver.
            return TemperatureSnapshot(
                None,
                None,
                SensorStatus(
                    provider="LibreHardwareMonitor",
                    available=False,
                    message=f"Temperature sensors unavailable: {exc}",
                ),
            )

    def _initialize(self) -> None:
        if not self._dll_path.exists():
            return

        try:
            self._prepare_assembly_path()
            import clr  # type: ignore[import-not-found]

            clr.AddReference(str(self._dll_path))
            from LibreHardwareMonitor.Hardware import Computer, SensorType  # type: ignore[import-not-found]

            computer = Computer()
            computer.IsCpuEnabled = True
            computer.IsMotherboardEnabled = True
            computer.IsStorageEnabled = True
            computer.Open()

            self._computer = computer
            self._sensor_type = SensorType
            self._status = SensorStatus(
                provider="LibreHardwareMonitor",
                available=True,
                message="LibreHardwareMonitor loaded; waiting for temperature sensors",
            )
        except Exception as exc:
            self._computer = None
            self._sensor_type = None
            self._status = SensorStatus(
                provider="LibreHardwareMonitor",
                available=False,
                message=f"Temperature sensors unavailable: {exc}",
            )

    def _prepare_assembly_path(self) -> None:
        vendor_dir = str(self._dll_path.parent)
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(vendor_dir)
        if vendor_dir not in sys.path:
            sys.path.insert(0, vendor_dir)

    def _iter_hardware(self, hardware_items: Any) -> Any:
        for hardware in hardware_items:
            self._update_hardware(hardware)
            yield hardware
            yield from self._iter_hardware(hardware.SubHardware)

    def _update_hardware(self, hardware: Any) -> None:
        hardware.Update()

    def _temperature_value(self, sensor: Any) -> float | None:
        raw_value = self._raw_temperature_value(sensor)
        if raw_value is None:
            return None
        return self._valid_temperature_value(raw_value)

    def _raw_temperature_value(self, sensor: Any) -> float | None:
        if self._sensor_type is not None and sensor.SensorType != self._sensor_type.Temperature:
            return None
        if self._sensor_type is None and str(sensor.SensorType).lower() != "temperature":
            return None
        if sensor.Value is None:
            return None
        return float(sensor.Value)

    @staticmethod
    def _valid_temperature_value(value: float) -> float | None:
        if value <= 0.0 or value > 125.0:
            return None
        return value

    @staticmethod
    def _classify_temperature_sensor(hardware_type: str, sensor_name: str) -> str | None:
        normalized_name = sensor_name.lower()
        if "cpu" in hardware_type:
            return "cpu"
        if "storage" in hardware_type or "hdd" in hardware_type:
            return "storage"
        if "motherboard" in hardware_type and (
            "cpu" in normalized_name
            or "package" in normalized_name
            or "tdie" in normalized_name
            or "tctl" in normalized_name
        ):
            return "cpu"
        return None

    def _build_status(
        self,
        cpu_temp: float | None,
        disk_temp: float | None,
        invalid_cpu_values: int = 0,
        invalid_storage_values: int = 0,
    ) -> SensorStatus:
        missing: list[str] = []
        if cpu_temp is None:
            missing.append("CPU")
        if disk_temp is None:
            missing.append("disk")
        if not missing:
            return SensorStatus("LibreHardwareMonitor", True, "OK")

        invalid: list[str] = []
        if cpu_temp is None and invalid_cpu_values:
            invalid.append("CPU returned invalid values")
        if disk_temp is None and invalid_storage_values:
            invalid.append("disk returned invalid values")
        if invalid:
            detail = "; ".join(invalid)
            return SensorStatus(
                "LibreHardwareMonitor",
                False,
                f"{detail}. Run as Administrator and compare with LibreHardwareMonitor GUI.",
            )

        return SensorStatus(
            "LibreHardwareMonitor",
            False,
            f"Sensor unavailable: {', '.join(missing)} temperature",
        )

    @staticmethod
    def _choose_cpu_temperature(values: list[tuple[str, float]]) -> float | None:
        if not values:
            return None

        package_values = [
            value
            for name, value in values
            if "package" in name.lower() or "tdie" in name.lower() or "tctl" in name.lower()
        ]
        if package_values:
            return max(package_values)
        return max(value for _, value in values)

    @staticmethod
    def _choose_max_temperature(values: list[tuple[str, float]]) -> float | None:
        if not values:
            return None
        return max(value for _, value in values)
