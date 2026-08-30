"""Application composition root and GUI-thread telemetry controller."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import Any, Callable

from PySide6 import QtCore, QtWidgets

from collectors.system_metrics import SystemMetrics, SystemMetricsCollector
from collectors.temperature import SensorStatus, TemperatureCollector, TemperatureSnapshot
from models.sample import HardwareSample, SampleHistory
from settings import SettingsAdapter
from ui.floating_monitor import FloatingMonitor
from windows_integration import restart_as_administrator


REFRESH_INTERVAL_MS = 1000
HISTORY_SECONDS = 10 * 60
WORKER_STOP_TIMEOUT_MS = 3000


@dataclass(frozen=True)
class CollectionFailure:
    """A recoverable cycle failure emitted by the worker."""

    failed_at: float
    message: str
    stage: str = "collection"
    exception_type: str = ""

    @property
    def timestamp(self) -> float:
        return self.failed_at

    @property
    def error(self) -> str:
        return self.message


@dataclass(frozen=True)
class TelemetryStatus:
    """Structured lifecycle/freshness state for the presentation layer."""

    phase: str
    message: str
    timestamp: float
    stale: bool = False
    last_success_timestamp: float | None = None
    failure: CollectionFailure | None = None

    @property
    def is_stale(self) -> bool:
        return self.stale

    @property
    def error(self) -> CollectionFailure | None:
        return self.failure


@dataclass(frozen=True)
class TelemetryState:
    status: TelemetryStatus
    sample: HardwareSample | None
    history: tuple[HardwareSample, ...]

    @property
    def last_sample(self) -> HardwareSample | None:
        return self.sample


SystemCollectorFactory = Callable[[], Any]
TemperatureCollectorFactory = Callable[[], Any]


class TelemetryWorker(QtCore.QObject):
    """Own native collectors and their timer on one non-GUI Qt thread."""

    sample_ready = QtCore.Signal(object)
    collection_failed = QtCore.Signal(object)
    finished = QtCore.Signal()

    def __init__(
        self,
        system_collector_factory: SystemCollectorFactory = SystemMetricsCollector,
        temperature_collector_factory: TemperatureCollectorFactory = TemperatureCollector,
        *,
        interval_ms: int = REFRESH_INTERVAL_MS,
        clock: Callable[[], float] = time.time,
        parent: QtCore.QObject | None = None,
        system_factory: SystemCollectorFactory | None = None,
        temperature_factory: TemperatureCollectorFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self._system_collector_factory = (
            system_collector_factory if system_factory is None else system_factory
        )
        self._temperature_collector_factory = (
            temperature_collector_factory if temperature_factory is None else temperature_factory
        )
        self._interval_ms = max(1, int(interval_ms))
        self._clock = clock
        self._stop_request = Event()
        self._started_event = Event()
        self._system_collector: Any | None = None
        self._temperature_collector: Any | None = None
        self._temperature_error = "Temperature provider unavailable"
        self._timer: QtCore.QTimer | None = None
        self._collecting = False
        self._stopping = False
        self._finished_emitted = False

    @property
    def timer(self) -> QtCore.QTimer | None:
        return self._timer

    @property
    def system_collector(self) -> Any | None:
        return self._system_collector

    @property
    def temperature_collector(self) -> Any | None:
        return self._temperature_collector

    @property
    def started_event(self) -> Event:
        return self._started_event

    @property
    def stop_event(self) -> Event:
        return self._stop_request

    @QtCore.Slot()
    def start(self) -> None:
        self._started_event.set()
        if self._stopping or self._timer is not None:
            return
        if self._stop_request.is_set():
            self.stop()
            return
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self.collect_once)
        # The first cycle is deliberately immediate, but it happens after the
        # worker has entered its thread and never blocks window construction.
        self.collect_once()
        if not self._stopping:
            self._timer.start()

    @QtCore.Slot()
    def collect_once(self) -> None:
        if self._stop_request.is_set() or self._stopping or self._collecting:
            return
        self._collecting = True
        try:
            system_collector = self._ensure_system_collector()
            if system_collector is None:
                return

            metrics = system_collector.collect()
            temperature = self._collect_temperature()
            sample = self._make_sample(metrics, temperature)
            self.sample_ready.emit(sample)
        except Exception as exc:
            self._emit_failure("collection", exc)
        finally:
            self._collecting = False

    @QtCore.Slot()
    def stop(self) -> None:
        if self._finished_emitted:
            return
        self._stop_request.set()
        self._stopping = True
        if self._timer is not None:
            self._timer.stop()

        # Close temperature first because it owns the managed/native provider;
        # optional close methods make fakes and future collectors compatible.
        self._close_collector(self._temperature_collector)
        self._close_collector(self._system_collector)
        self._temperature_collector = None
        self._system_collector = None

        self._finished_emitted = True
        self.finished.emit()

    def request_stop(self) -> None:
        """Thread-safe stop intent; actual close runs in worker affinity."""

        self._stop_request.set()

    def _ensure_system_collector(self) -> Any | None:
        if self._system_collector is not None:
            return self._system_collector
        try:
            collector = self._system_collector_factory()
            if collector is None:
                raise RuntimeError("System metrics collector factory returned None")
            self._system_collector = collector
            return self._system_collector
        except Exception as exc:
            self._emit_failure("system initialization", exc)
            return None

    def _ensure_temperature_collector(self) -> Any | None:
        if self._temperature_collector is not None:
            return self._temperature_collector
        try:
            collector = self._temperature_collector_factory()
            if collector is None:
                raise RuntimeError("Temperature collector factory returned None")
            self._temperature_collector = collector
            return self._temperature_collector
        except Exception as exc:
            # Temperature access is optional: retain a valid CPU/MEM/disk
            # sample and expose the provider failure as structured status.
            self._temperature_error = str(exc)
            return None

    def _collect_temperature(self) -> TemperatureSnapshot:
        collector = self._ensure_temperature_collector()
        if collector is None:
            return TemperatureSnapshot(
                None,
                None,
                SensorStatus("LibreHardwareMonitor", False, self._temperature_error),
            )
        try:
            snapshot = collector.collect()
            if isinstance(snapshot, TemperatureSnapshot):
                return TemperatureSnapshot(
                    snapshot.cpu_temp_c,
                    snapshot.disk_temp_c,
                    self._coerce_sensor_status(snapshot.status),
                )
            # Accept duck-typed fakes while preserving a typed result for the
            # rest of this worker.
            status = self._coerce_sensor_status(getattr(snapshot, "status", None))
            return TemperatureSnapshot(
                getattr(snapshot, "cpu_temp_c", None),
                getattr(snapshot, "disk_temp_c", None),
                status,
            )
        except Exception as exc:
            self._temperature_error = str(exc)
            return TemperatureSnapshot(
                None,
                None,
                SensorStatus("LibreHardwareMonitor", False, f"Temperature sensors unavailable: {exc}"),
            )

    @staticmethod
    def _coerce_sensor_status(status: Any) -> SensorStatus:
        if isinstance(status, SensorStatus):
            return status
        if status is None:
            return SensorStatus("LibreHardwareMonitor", False, "Temperature provider returned no status")
        return SensorStatus(
            str(getattr(status, "provider", "LibreHardwareMonitor")),
            bool(getattr(status, "available", False)),
            str(getattr(status, "message", status)),
        )

    def _make_sample(self, metrics: SystemMetrics, temperature: TemperatureSnapshot) -> HardwareSample:
        status = temperature.status
        sensor_message = status.message
        return HardwareSample(
            timestamp=float(self._clock()),
            cpu_percent=float(metrics.cpu_percent),
            memory_percent=float(metrics.memory_percent),
            memory_used_gb=float(metrics.memory_used_gb),
            memory_total_gb=float(metrics.memory_total_gb),
            disk_usage_percent=float(metrics.disk_usage_percent),
            disk_read_mb_s=float(metrics.disk_read_mb_s),
            disk_write_mb_s=float(metrics.disk_write_mb_s),
            disk_active_percent=float(metrics.disk_active_percent),
            cpu_temp_c=temperature.cpu_temp_c,
            disk_temp_c=temperature.disk_temp_c,
            sensor_status=sensor_message,
            sensor_provider=status.provider,
            sensor_available=bool(status.available),
            sensor_message=sensor_message,
            disk_capacity_path=getattr(metrics, "disk_capacity_path", ""),
            disk_io_scope=getattr(metrics, "disk_io_scope", "all disks"),
        )

    def _emit_failure(self, stage: str, exc: Exception) -> None:
        self.collection_failed.emit(
            CollectionFailure(
                failed_at=float(self._clock()),
                message=str(exc) or exc.__class__.__name__,
                stage=stage,
                exception_type=exc.__class__.__name__,
            )
        )

    @staticmethod
    def _close_collector(collector: Any | None) -> None:
        if collector is None:
            return
        close_method = getattr(collector, "close", None)
        if callable(close_method):
            try:
                close_method()
            except Exception:
                # Shutdown must continue for the other collector and thread.
                pass


class MonitorController(QtCore.QObject):
    """Aggregate worker samples and own history on the GUI thread."""

    sample_ready = QtCore.Signal(object, object)
    collection_failed = QtCore.Signal(object)
    status_changed = QtCore.Signal(object)
    state_changed = QtCore.Signal(object)
    stopped = QtCore.Signal(bool)
    _stop_worker_requested = QtCore.Signal()
    _collect_worker_requested = QtCore.Signal()

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        *,
        system_collector_factory: SystemCollectorFactory = SystemMetricsCollector,
        temperature_collector_factory: TemperatureCollectorFactory = TemperatureCollector,
        interval_ms: int = REFRESH_INTERVAL_MS,
        history_seconds: float = HISTORY_SECONDS,
        clock: Callable[[], float] = time.time,
        worker_factory: Callable[..., TelemetryWorker] = TelemetryWorker,
        system_factory: SystemCollectorFactory | None = None,
        temperature_factory: TemperatureCollectorFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self._system_collector_factory = (
            system_collector_factory if system_factory is None else system_factory
        )
        self._temperature_collector_factory = (
            temperature_collector_factory if temperature_factory is None else temperature_factory
        )
        self._interval_ms = interval_ms
        self._clock = clock
        self._worker_factory = worker_factory
        self._history = SampleHistory(history_seconds)
        self._thread: QtCore.QThread | None = None
        self._worker: TelemetryWorker | None = None
        self._last_sample: HardwareSample | None = None
        self._last_status: TelemetryStatus | None = None
        self._stopping = False
        self._stop_requested = False
        self._stopped_emitted = False
        self._stop_event: Event | None = None
        self._worker_started_event: Event | None = None
        self._retired_workers: list[TelemetryWorker] = []

    @property
    def history(self) -> tuple[HardwareSample, ...]:
        return self._history.as_tuple()

    @property
    def last_sample(self) -> HardwareSample | None:
        return self._last_sample

    @property
    def status(self) -> TelemetryStatus | None:
        return self._last_status

    @property
    def worker_thread(self) -> QtCore.QThread | None:
        return self._thread

    @property
    def worker(self) -> TelemetryWorker | None:
        return self._worker

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self._stopping = False
        self._stop_requested = False
        self._stopped_emitted = False
        self._publish_status(
            TelemetryStatus(
                phase="starting",
                message="Starting…",
                timestamp=float(self._clock()),
            )
        )

        thread = QtCore.QThread(self)
        worker = self._worker_factory(
            self._system_collector_factory,
            self._temperature_collector_factory,
            interval_ms=self._interval_ms,
            clock=self._clock,
        )
        worker.moveToThread(thread)
        worker.sample_ready.connect(self._on_sample)
        worker.collection_failed.connect(self._on_failure)
        thread.finished.connect(self._on_thread_finished)
        thread.started.connect(worker.start)
        # Establish the queued handoff before starting the thread.  Emitting a
        # Qt signal to a receiver that finishes concurrently is lifecycle-safe;
        # invoking a deleted Python/C++ wrapper is not.
        self._stop_worker_requested.connect(
            worker.stop,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        self._collect_worker_requested.connect(
            worker.collect_once,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )
        # Standard Qt worker lifecycle: finished is emitted in the worker
        # thread, quits that thread directly, and the thread's finished signal
        # schedules deletion of the worker object.  A retired Python wrapper
        # guard keeps the last reference alive while that signal chain settles.
        worker.finished.connect(thread.quit, QtCore.Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater, QtCore.Qt.ConnectionType.DirectConnection)
        self._thread = thread
        self._worker = worker
        # Keep the thread-safe handoff primitives independent of the QObject
        # wrapper.  They remain valid even if worker.start() finishes and Qt
        # deletes the worker before a GUI stop call returns.
        self._stop_event = getattr(worker, "stop_event", None)
        self._worker_started_event = getattr(worker, "started_event", None)
        thread.start()

    def collect_once(self) -> None:
        """Request a cycle without ever calling a collector from the GUI."""

        worker = self._worker
        thread = self._thread
        if worker is None or thread is None or not thread.isRunning():
            return
        self._collect_worker_requested.emit()

    def stop(self, timeout_ms: int = WORKER_STOP_TIMEOUT_MS) -> bool:
        """Request worker shutdown and report whether it completed.

        A native provider can block a worker thread beyond the bounded wait.
        In that case ownership is deliberately retained; the already-queued
        ``worker.stop`` closes collectors after the call returns and the
        thread's ``finished`` signal performs final reference cleanup.
        """

        self._stopping = True
        thread = self._thread
        worker = self._worker
        if thread is None:
            self._emit_stopped(True)
            return True

        if worker is not None and thread.isRunning():
            if not getattr(self, "_stop_requested", False):
                self._stop_requested = True
                if self._stop_event is not None:
                    self._stop_event.set()
                self._stop_worker_requested.emit()
            if not thread.wait(max(1, int(timeout_ms))):
                # Do not terminate or quit a thread while managed code could
                # be inside a provider call.  The queued stop remains pending
                # and will close collectors once the call returns.
                return False
        elif worker is not None:
            # The QThread may still be between start() and its run loop.  Only
            # set a thread-safe stop intent here; the worker's started slot
            # performs close() in its own affinity thread.
            if self._stop_event is not None:
                self._stop_event.set()
            if thread.isFinished():
                self._clear_finished_thread(thread)
                self._emit_stopped(True)
                return True
            return False
        elif thread.isRunning():
            # There is no worker to close, but retain the same ownership rule
            # and let the thread's own finish path determine cleanup.
            if not thread.wait(max(1, int(timeout_ms))):
                return False

        if thread.isRunning():
            return False
        self._clear_finished_thread(thread)
        self._emit_stopped(True)
        return True

    def wait_for_stop(self) -> bool:
        """Safely finish an already-requested stop, waiting without a deadline.

        This is reserved for the final ``aboutToQuit`` safety net.  It never
        terminates a thread; if a native call is still blocking, process
        teardown waits until that call returns and the worker closes it.
        """

        thread = self._thread
        if thread is None:
            self._emit_stopped(True)
            return True
        if not self._stop_requested:
            self._stopping = True
            self._stop_requested = True
            if thread.isRunning() and self._worker is not None:
                if self._stop_event is not None:
                    self._stop_event.set()
                self._stop_worker_requested.emit()
            elif self._worker is not None:
                if self._stop_event is not None:
                    self._stop_event.set()
        if not thread.isRunning() and thread.isFinished():
            self._clear_finished_thread(thread)
            self._emit_stopped(True)
            return True
        if not thread.isRunning() and not thread.isFinished() and self._worker_started_event is not None:
            # start() was already requested, but the OS thread has not yet
            # entered its run loop.  Wait for that hand-off rather than
            # dropping references or invoking a worker slot from the GUI.
            self._worker_started_event.wait()
        while thread.isRunning():
            thread.wait(100)
        while not thread.isFinished():
            thread.wait(100)
        self._clear_finished_thread(thread)
        self._emit_stopped(True)
        return True

    @QtCore.Slot()
    def _on_thread_finished(self) -> None:
        thread = self.sender()
        if thread is self._thread and thread is not None and not thread.isRunning():
            self._clear_finished_thread(thread)
            self._emit_stopped(True)

    def _clear_finished_thread(self, thread: QtCore.QThread) -> None:
        if thread is not self._thread:
            return
        worker = self._worker
        if worker is not None and worker not in self._retired_workers:
            self._retired_workers.append(worker)
        self._thread = None
        self._worker = None
        self._stop_requested = False
        self._stop_event = None
        self._worker_started_event = None

    def _emit_stopped(self, success: bool) -> None:
        if success and self._stopped_emitted:
            return
        if success:
            self._stopped_emitted = True
        self.stopped.emit(success)

    @QtCore.Slot(object)
    def _on_sample(self, sample: HardwareSample) -> None:
        if self._stopping:
            return
        self._last_sample = sample
        self._history.append(sample)
        history = self._history.as_tuple()
        self.sample_ready.emit(sample, history)
        self._publish_status(
            TelemetryStatus(
                phase="updated",
                message=f"Updated {datetime.fromtimestamp(sample.timestamp).strftime('%H:%M:%S')}",
                timestamp=sample.timestamp,
                last_success_timestamp=sample.timestamp,
            )
        )

    @QtCore.Slot(object)
    def _on_failure(self, failure: CollectionFailure) -> None:
        if self._stopping:
            return
        self.collection_failed.emit(failure)
        message = "Update failed — showing last sample" if self._last_sample is not None else "Update failed — retrying"
        self._publish_status(
            TelemetryStatus(
                phase="stale" if self._last_sample is not None else "error",
                message=message,
                timestamp=failure.failed_at,
                stale=self._last_sample is not None,
                last_success_timestamp=self._last_sample.timestamp if self._last_sample else None,
                failure=failure,
            )
        )

    def _publish_status(self, status: TelemetryStatus) -> None:
        self._last_status = status
        self.status_changed.emit(status)
        self.state_changed.emit(TelemetryState(status, self._last_sample, self.history))


class ApplicationQuitCoordinator(QtCore.QObject):
    """Coordinate an application quit without detaching a live worker."""

    def __init__(
        self,
        application: QtWidgets.QApplication,
        controller: MonitorController,
        window: FloatingMonitor,
        tray: "TrayController | None" = None,
    ) -> None:
        super().__init__(application)
        self._application = application
        self._controller = controller
        self._window = window
        self._tray = tray
        self._quitting = False
        self._completed = False

    @QtCore.Slot()
    def request(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._controller.stopped.connect(self._on_stopped)
        if self._controller.stop(timeout_ms=0):
            self._on_stopped(True)
        else:
            self._window.show_shutdown_pending()

    @QtCore.Slot(bool)
    def _on_stopped(self, success: bool) -> None:
        if not success or self._completed:
            return
        self._completed = True
        try:
            self._controller.stopped.disconnect(self._on_stopped)
        except (RuntimeError, TypeError):
            pass
        self._window.finish_quit()
        if self._tray is not None:
            self._tray.close()
        self._application.quit()


class TrayController(QtCore.QObject):
    """Optional tray lifecycle with a deterministic no-tray fallback."""

    def __init__(
        self,
        window: FloatingMonitor,
        app: QtWidgets.QApplication,
        *,
        tray_available: bool | None = None,
    ) -> None:
        super().__init__(app)
        self.window = window
        self.app = app
        self.icon: QtWidgets.QSystemTrayIcon | None = None
        self.available = (
            bool(QtWidgets.QSystemTrayIcon.isSystemTrayAvailable())
            if tray_available is None
            else bool(tray_available)
        )
        if not self.available:
            window.set_tray_available(False)
            return

        icon = QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)
        tray = QtWidgets.QSystemTrayIcon(icon, self)
        menu = QtWidgets.QMenu()
        show_action = menu.addAction("Show")
        hide_action = menu.addAction("Hide")
        menu.addSeparator()
        restart_action = menu.addAction("Restart as administrator")
        restart_action.triggered.connect(window.request_restart_as_admin)
        quit_action = menu.addAction("Quit")
        show_action.triggered.connect(self.show)
        hide_action.triggered.connect(self.hide)
        quit_action.triggered.connect(self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._activated)
        tray.setToolTip("Hardware Floating Monitor")
        tray.show()
        self.icon = tray
        window.set_tray_available(True)

    @QtCore.Slot()
    def show(self) -> None:
        self.window.show_from_tray()

    @QtCore.Slot()
    def hide(self) -> None:
        self.window.hide()

    @QtCore.Slot()
    def quit(self) -> None:
        self.window.request_quit()

    @QtCore.Slot(QtWidgets.QSystemTrayIcon.ActivationReason)
    def _activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
            QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.show()

    def close(self) -> None:
        if self.icon is not None:
            self.icon.hide()


def run_app() -> int:
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    application.setApplicationName("Hardware Floating Monitor")
    application.setOrganizationName("D-sudoasd")

    settings = SettingsAdapter()
    window = FloatingMonitor(settings=settings)
    controller = MonitorController()
    tray = TrayController(window, application)
    # Application-owned quit coordination below must run for both tray and
    # no-tray configurations; do not let Qt auto-quit before the worker has
    # acknowledged its stop request.
    application.setQuitOnLastWindowClosed(False)

    quit_coordinator = ApplicationQuitCoordinator(application, controller, window, tray)
    window.quit_requested.connect(quit_coordinator.request)
    window.restart_as_admin_requested.connect(lambda: _restart_from_window(quit_coordinator.request))
    controller.sample_ready.connect(window.update_sample)
    controller.status_changed.connect(window.update_status)

    def shutdown() -> None:
        window.save_settings()
        # A direct external application.quit() cannot be cancelled once
        # aboutToQuit fires.  Finish the existing request synchronously here,
        # without terminate()/thread.quit(), so Qt never destroys a live
        # worker thread during process teardown.
        if not controller.stop(timeout_ms=0):
            controller.wait_for_stop()
        tray.close()

    application.aboutToQuit.connect(shutdown)
    window.set_starting()
    window.show()
    controller.start()
    return application.exec()


def _restart_from_window(on_success_quit: Callable[[], None] | None = None) -> None:
    result = restart_as_administrator()
    if result.started:
        if on_success_quit is not None:
            on_success_quit()
        else:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.quit()
        return
    parent = QtWidgets.QApplication.activeWindow()
    QtWidgets.QMessageBox.warning(
        parent,
        "Administrator restart not started",
        result.message or "The current monitor will continue running.",
    )
