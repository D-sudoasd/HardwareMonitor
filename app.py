from __future__ import annotations

import sys
import time
from collections import deque
from typing import Deque

from PySide6 import QtCore, QtWidgets

from collectors.system_metrics import SystemMetricsCollector
from collectors.temperature import TemperatureCollector
from models.sample import HardwareSample
from ui.floating_monitor import FloatingMonitor


REFRESH_INTERVAL_MS = 1000
HISTORY_SECONDS = 10 * 60


class MonitorController(QtCore.QObject):
    sample_ready = QtCore.Signal(object, object)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._system_collector = SystemMetricsCollector()
        self._temperature_collector = TemperatureCollector()
        self._history: Deque[HardwareSample] = deque()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.collect_once)

    @property
    def history(self) -> tuple[HardwareSample, ...]:
        return tuple(self._history)

    def start(self) -> None:
        self.collect_once()
        self._timer.start()

    @QtCore.Slot()
    def collect_once(self) -> None:
        metrics = self._system_collector.collect()
        temperatures = self._temperature_collector.collect()
        sample = HardwareSample(
            timestamp=time.time(),
            cpu_percent=metrics.cpu_percent,
            memory_percent=metrics.memory_percent,
            memory_used_gb=metrics.memory_used_gb,
            memory_total_gb=metrics.memory_total_gb,
            disk_usage_percent=metrics.disk_usage_percent,
            disk_read_mb_s=metrics.disk_read_mb_s,
            disk_write_mb_s=metrics.disk_write_mb_s,
            disk_active_percent=metrics.disk_active_percent,
            cpu_temp_c=temperatures.cpu_temp_c,
            disk_temp_c=temperatures.disk_temp_c,
            sensor_status=temperatures.status.message,
        )
        self._history.append(sample)
        self._trim_history(sample.timestamp)
        self.sample_ready.emit(sample, tuple(self._history))

    def _trim_history(self, now: float) -> None:
        cutoff = now - HISTORY_SECONDS
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()


def run_app() -> int:
    application = QtWidgets.QApplication(sys.argv)
    application.setApplicationName("Hardware Floating Monitor")

    try:
        controller = MonitorController()
    except RuntimeError as exc:
        QtWidgets.QMessageBox.critical(
            None,
            "Hardware monitor cannot start",
            str(exc),
        )
        return 1

    window = FloatingMonitor()
    controller.sample_ready.connect(window.update_sample)
    window.show()
    controller.start()

    return application.exec()
