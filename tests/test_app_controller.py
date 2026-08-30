from __future__ import annotations

import time
from threading import Event
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from app import ApplicationQuitCoordinator, MonitorController, TelemetryWorker
from collectors.system_metrics import SystemMetrics
from collectors.temperature import SensorStatus, TemperatureSnapshot
from settings import SettingsAdapter
from ui.floating_monitor import FloatingMonitor


@pytest.fixture
def qapp() -> QtWidgets.QApplication:
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-tests"])
    return application


def _metrics(value: float = 10.0) -> SystemMetrics:
    return SystemMetrics(value, value, 1.0, 8.0, value, 130.0, 42.0, value, "C:\\", "all disks")


class StableTemperature:
    def collect(self) -> TemperatureSnapshot:
        return TemperatureSnapshot(50.0, 42.0, SensorStatus("fake", True, "OK"))

    def close(self) -> None:
        return None


def _process_until(application: QtWidgets.QApplication, predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        application.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 10)
        time.sleep(0.002)
    return bool(predicate())


def test_worker_retries_after_failure_and_keeps_history_on_gui_thread(qapp: QtWidgets.QApplication) -> None:
    class FlakySystem:
        def __init__(self) -> None:
            self.calls = 0
            self.call_threads: list[QtCore.QThread] = []
            self.close_count = 0

        def collect(self) -> SystemMetrics:
            self.calls += 1
            self.call_threads.append(QtCore.QThread.currentThread())
            if self.calls == 2:
                raise OSError("temporary psutil failure")
            return _metrics(float(self.calls))

        def close(self) -> None:
            self.close_count += 1

    class ClosableTemperature(StableTemperature):
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    system = FlakySystem()
    temperature = ClosableTemperature()
    samples = []
    failures = []
    statuses = []
    stopped: list[bool] = []
    controller = MonitorController(
        system_collector_factory=lambda: system,
        temperature_collector_factory=lambda: temperature,
        interval_ms=15,
    )
    controller.sample_ready.connect(lambda sample, history: samples.append((sample, history)))
    controller.collection_failed.connect(failures.append)
    controller.status_changed.connect(statuses.append)
    controller.stopped.connect(stopped.append)

    controller.start()
    assert _process_until(qapp, lambda: len(samples) >= 2 and bool(failures))
    assert len(controller.history) == len(samples)
    assert controller.last_sample is samples[-1][0]
    assert any(status.phase == "stale" and status.stale for status in statuses)
    assert any(status.message == "Update failed — showing last sample" for status in statuses)
    assert system.call_threads
    assert all(thread != qapp.thread() for thread in system.call_threads)

    controller.stop()
    controller.stop()
    assert controller.worker_thread is None
    assert controller.worker is None
    assert system.close_count == 1
    assert temperature.close_count == 1
    assert stopped == [True]


def test_slow_native_collection_does_not_block_gui_timer(qapp: QtWidgets.QApplication) -> None:
    class SlowSystem:
        def collect(self) -> SystemMetrics:
            time.sleep(0.20)
            return _metrics()

    controller = MonitorController(
        system_collector_factory=SlowSystem,
        temperature_collector_factory=StableTemperature,
        interval_ms=20,
    )
    callback_times: list[float] = []
    QtCore.QTimer.singleShot(25, lambda: callback_times.append(time.monotonic()))
    controller.start()
    started = time.monotonic()
    assert _process_until(qapp, lambda: bool(callback_times), timeout=0.12)
    assert callback_times[0] - started < 0.12
    controller.stop()


def test_offscreen_startup_shows_starting_state_and_shuts_down(
    qapp: QtWidgets.QApplication,
    tmp_path: Path,
) -> None:
    ini = tmp_path / "test-settings.ini"
    qsettings = QtCore.QSettings(str(ini), QtCore.QSettings.Format.IniFormat)
    window = FloatingMonitor(settings=SettingsAdapter(qsettings), tray_available=False)
    controller = MonitorController(
        system_collector_factory=lambda: type("System", (), {"collect": lambda self: _metrics()})(),
        temperature_collector_factory=StableTemperature,
        interval_ms=25,
    )
    controller.status_changed.connect(window.update_status)
    controller.sample_ready.connect(window.update_sample)
    window.set_starting()
    window.show()
    assert window._status_label.text() == "Starting…"
    controller.start()
    QtCore.QTimer.singleShot(80, qapp.quit)
    qapp.exec()
    controller.stop()

    assert controller.worker_thread is None
    assert controller.worker is None
    window.deleteLater()


def test_stop_timeout_retains_thread_until_blocking_collector_releases(qapp: QtWidgets.QApplication) -> None:
    class BlockingSystem:
        def __init__(self) -> None:
            self.entered = Event()
            self.release = Event()
            self.close_count = 0

        def collect(self) -> SystemMetrics:
            self.entered.set()
            self.release.wait(2.0)
            return _metrics()

        def close(self) -> None:
            self.close_count += 1

    class ClosableTemperature(StableTemperature):
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    system = BlockingSystem()
    temperature = ClosableTemperature()
    controller = MonitorController(
        system_collector_factory=lambda: system,
        temperature_collector_factory=lambda: temperature,
        interval_ms=1000,
    )
    controller.start()
    assert system.entered.wait(1.0)

    stopped: list[bool] = []
    controller.stopped.connect(stopped.append)
    assert controller.stop(timeout_ms=20) is False
    assert controller.stop(timeout_ms=20) is False
    assert controller.worker_thread is not None
    assert controller.worker is not None
    assert controller.worker_thread.isRunning()
    assert system.close_count == 0

    system.release.set()
    assert _process_until(qapp, lambda: controller.worker_thread is None, timeout=2.0)
    assert system.close_count == 1
    assert temperature.close_count == 1
    assert stopped == [True]
    assert controller.stop(timeout_ms=20) is True
    assert stopped == [True]


def test_stopped_signal_is_emitted_once_for_repeated_stop_calls(qapp: QtWidgets.QApplication) -> None:
    controller = MonitorController()
    stopped: list[bool] = []
    controller.stopped.connect(stopped.append)

    assert controller.stop() is True
    assert controller.stop() is True

    assert stopped == [True]


def test_start_then_immediate_stop_does_not_call_worker_from_gui_thread(qapp: QtWidgets.QApplication) -> None:
    class ClosableSystem:
        def __init__(self) -> None:
            self.close_count = 0
            self.close_thread: QtCore.QThread | None = None

        def collect(self) -> SystemMetrics:
            return _metrics()

        def close(self) -> None:
            self.close_count += 1
            self.close_thread = QtCore.QThread.currentThread()

    system = ClosableSystem()
    stopped: list[bool] = []
    controller = MonitorController(
        system_collector_factory=lambda: system,
        temperature_collector_factory=StableTemperature,
        interval_ms=1000,
    )
    controller.stopped.connect(stopped.append)

    controller.start()
    result = controller.stop(timeout_ms=0)
    if not result:
        assert _process_until(qapp, lambda: controller.worker_thread is None, timeout=1.0)

    assert controller.worker_thread is None
    assert controller.worker is None
    assert stopped == [True]
    assert system.close_count in {0, 1}
    if system.close_thread is not None:
        assert system.close_thread != qapp.thread()


def test_stop_intent_blocks_a_queued_collection_cycle() -> None:
    calls: list[str] = []

    class System:
        def collect(self) -> SystemMetrics:
            calls.append("collect")
            return _metrics()

    worker = TelemetryWorker(System, StableTemperature)
    worker.request_stop()
    worker.collect_once()

    assert calls == []


def test_application_quit_coordinator_keeps_no_tray_window_visible_while_blocked(
    qapp: QtWidgets.QApplication,
    tmp_path: Path,
) -> None:
    class BlockingSystem:
        def __init__(self) -> None:
            self.entered = Event()
            self.release = Event()
            self.close_count = 0

        def collect(self) -> SystemMetrics:
            self.entered.set()
            self.release.wait(2.0)
            return _metrics()

        def close(self) -> None:
            self.close_count += 1

    class FakeApplication(QtCore.QObject):
        def __init__(self) -> None:
            super().__init__()
            self.quit_count = 0

        def quit(self) -> None:
            self.quit_count += 1

    system = BlockingSystem()
    controller = MonitorController(
        system_collector_factory=lambda: system,
        temperature_collector_factory=StableTemperature,
        interval_ms=1000,
    )
    qsettings = QtCore.QSettings(str(tmp_path / "test-settings-coordinator.ini"), QtCore.QSettings.Format.IniFormat)
    window = FloatingMonitor(settings=SettingsAdapter(qsettings), tray_available=False)
    fake_application = FakeApplication()
    coordinator = ApplicationQuitCoordinator(fake_application, controller, window)
    window.quit_requested.connect(coordinator.request)
    controller.start()
    assert system.entered.wait(1.0)
    window.show()
    qapp.processEvents()

    # The close event is intentionally ignored while the coordinator keeps a
    # visible WAIT surface for the blocked collector.
    assert window.close() is False
    assert fake_application.quit_count == 0
    assert window.isVisible()
    assert window._shutdown_pending
    assert window._status_label.text() == "Waiting for collector to return…"

    system.release.set()
    assert _process_until(qapp, lambda: fake_application.quit_count == 1, timeout=2.0)
    assert controller.worker_thread is None
    assert system.close_count == 1
    assert not window.isVisible()
    window.deleteLater()
