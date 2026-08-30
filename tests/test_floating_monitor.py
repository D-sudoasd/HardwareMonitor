from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from app import CollectionFailure, TelemetryStatus
from models.sample import HardwareSample
from settings import SettingsAdapter
from ui.floating_monitor import FloatingMonitor, TrendChart, _format_io_rate_compact


def _sample(timestamp: float, *, available: bool = True) -> HardwareSample:
    return HardwareSample(
        timestamp=timestamp,
        cpu_percent=12.3,
        memory_percent=45.6,
        memory_used_gb=7.2,
        memory_total_gb=16.0,
        disk_usage_percent=78.9,
        disk_read_mb_s=130.0,
        disk_write_mb_s=42.0,
        disk_active_percent=50.0,
        cpu_temp_c=61.0,
        disk_temp_c=49.0,
        sensor_status="OK" if available else "provider unavailable",
        sensor_provider="fake",
        sensor_available=available,
        sensor_message="OK" if available else "No sensor permission",
        disk_capacity_path="C:\\",
        disk_io_scope="all disks",
    )


def test_ui_uses_truthful_disk_scopes_and_keeps_io_value_readable(tmp_path: Path) -> None:
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-ui-tests"])
    qsettings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = FloatingMonitor(settings=SettingsAdapter(qsettings))
    sample = _sample(100.0)

    window.update_sample(sample, (sample, _sample(110.0)))

    assert window._disk_metric._title.text() == "SYS C:"
    assert window._io_metric._title.text() == "IO ALL"
    assert window._io_metric.value_label.text() == "R130/W42"
    assert "IO all disks" in window._detail_line_2.text()
    assert window._chart.legend == ("CPU", "MEM", "DISK ACTIVE")
    assert window._chart.time_labels == ("10 min", "now")
    assert window._io_metric.value_label.sizeHint().width() <= window._io_metric.width()
    window.deleteLater()


def test_io_formatter_has_bounded_scientific_fallback_and_safe_non_finite_values() -> None:
    assert _format_io_rate_compact(130.0) == "130"
    assert _format_io_rate_compact(130_000.0).endswith("G")
    assert _format_io_rate_compact(1e20) == "1e20"
    assert len(_format_io_rate_compact(1e20)) <= 5
    assert len(_format_io_rate_compact(-1e20)) <= 5
    assert _format_io_rate_compact(float("nan")) == "N/A"
    assert _format_io_rate_compact(float("inf")) == "N/A"


def test_ui_keyboard_toggle_and_escape_collapse(tmp_path: Path) -> None:
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-keyboard-tests"])
    qsettings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = FloatingMonitor(settings=SettingsAdapter(qsettings))
    assert window.expanded is False

    enter = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Return,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    window.keyPressEvent(enter)
    assert window.expanded is True

    escape = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    window.keyPressEvent(escape)
    assert window.expanded is False
    window.deleteLater()


def test_trend_chart_uses_sample_timestamps_for_x_coordinates() -> None:
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-chart-tests"])
    samples = (_sample(0.0), _sample(1.0), _sample(9.0))
    xs = TrendChart._timestamp_xs(samples, 0.0, 100.0)

    assert xs == pytest.approx([591.0 / 600.0 * 100.0, 592.0 / 600.0 * 100.0, 100.0])

    rollback_xs = TrendChart._timestamp_xs((_sample(105.0), _sample(111.0), _sample(106.0)), 0.0, 100.0)
    assert rollback_xs == pytest.approx([99.0, 595.0 / 6.0, 100.0])

    full_span_xs = TrendChart._timestamp_xs((_sample(0.0), _sample(300.0), _sample(600.0)), 0.0, 100.0)
    assert full_span_xs == pytest.approx([0.0, 50.0, 100.0])

    duplicate_xs = TrendChart._timestamp_xs((_sample(100.0), _sample(100.0), _sample(200.0)), 0.0, 100.0)
    assert duplicate_xs[0] == duplicate_xs[1]

    clamped_xs = TrendChart._timestamp_xs((_sample(-1_000.0), _sample(0.0)), 0.0, 100.0)
    assert clamped_xs == pytest.approx([0.0, 100.0])


def test_pin_toggle_preserves_hidden_and_visible_window_states(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-pin-tests"])
    hidden_settings = QtCore.QSettings(str(tmp_path / "hidden.ini"), QtCore.QSettings.Format.IniFormat)
    hidden_window = FloatingMonitor(settings=SettingsAdapter(hidden_settings), tray_available=True)
    hidden_quit_events: list[bool] = []
    hidden_window.quit_requested.connect(lambda: hidden_quit_events.append(True))

    assert hidden_window.isVisible() is False
    hidden_window._pin_changed(False)
    app.processEvents()

    assert hidden_window.isVisible() is False
    assert hidden_quit_events == []

    visible_settings = QtCore.QSettings(str(tmp_path / "visible.ini"), QtCore.QSettings.Format.IniFormat)
    visible_window = FloatingMonitor(settings=SettingsAdapter(visible_settings), tray_available=False)
    visible_quit_events: list[bool] = []
    visible_window.quit_requested.connect(lambda: visible_quit_events.append(True))
    visible_window.show()
    app.processEvents()
    assert visible_window.isVisible() is True

    visible_window._pin_changed(False)
    app.processEvents()

    assert visible_window.isVisible() is True
    assert visible_quit_events == []
    hidden_window.deleteLater()
    visible_window.deleteLater()


def test_reset_position_persists_live_window_opacity(tmp_path: Path) -> None:
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-reset-position-tests"])
    qsettings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    settings = SettingsAdapter(qsettings)
    window = FloatingMonitor(settings=settings, tray_available=False)

    window.setWindowOpacity(0.83)
    live_opacity = window.windowOpacity()
    window.reset_position()

    assert settings.load().opacity == pytest.approx(live_opacity)
    window.deleteLater()


def test_no_tray_close_is_a_real_quit_path(tmp_path: Path) -> None:
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-tray-fallback-tests"])
    qsettings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = FloatingMonitor(settings=SettingsAdapter(qsettings), tray_available=False)
    quit_events: list[bool] = []
    window.quit_requested.connect(lambda: quit_events.append(True))

    assert window.close() is True
    assert quit_events == [True]


def test_expanded_stale_status_and_extreme_io_do_not_overlap_controls(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-geometry-tests"])
    qsettings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    window = FloatingMonitor(settings=SettingsAdapter(qsettings), tray_available=False)
    sample = HardwareSample(
        timestamp=100.0,
        cpu_percent=20.0,
        memory_percent=40.0,
        memory_used_gb=6.5,
        memory_total_gb=16.0,
        disk_usage_percent=72.0,
        disk_read_mb_s=1_000_000_000.0,
        disk_write_mb_s=987_654_321.0,
        disk_active_percent=50.0,
        cpu_temp_c=61.5,
        disk_temp_c=49.0,
        sensor_status="OK",
        sensor_provider="fake",
        sensor_available=True,
        sensor_message="OK",
        disk_capacity_path="C:\\",
        disk_io_scope="all disks",
    )
    window.update_sample(sample, (sample,))
    window.update_status(
        TelemetryStatus(
            phase="stale",
            message="Update failed — showing last sample",
            timestamp=101.0,
            stale=True,
            last_success_timestamp=100.0,
            failure=CollectionFailure(101.0, "disk vanished", "collection", "OSError"),
        )
    )
    window._set_expanded(True)
    window.show()
    app.processEvents()

    assert window._status_label.wordWrap() is True
    assert window._status_label.text() == "Update failed — showing last sample"
    assert window._status_label.geometry().right() <= window._details.rect().right()
    controls = (window._opacity_slider, window._auto_collapse_checkbox, window._pin_checkbox, window._menu_button, window._hide_button)
    assert all(not window._status_label.geometry().intersects(control.geometry()) for control in controls)
    assert window._io_metric.value_label.sizeHint().width() <= window._io_metric.value_label.width()
    assert "1,000,000,000.000 MB/s" in window._io_metric.value_label.toolTip()
    assert window._hide_button.text() == "Quit (no tray available)"
    assert window._hide_button.accessibleName() == "Quit (no tray available)"
    max_sample = replace(
        sample,
        disk_read_mb_s=sys.float_info.max,
        disk_write_mb_s=-sys.float_info.max,
    )
    window.update_sample(max_sample, (max_sample,))
    assert window._io_metric.value_label.text() == "R2e308/W-MAX"
    assert window._io_metric.value_label.sizeHint().width() <= window._io_metric.value_label.width()
    assert f"{sys.float_info.max:,.3f} MB/s" in window._io_metric.value_label.toolTip()
    assert f"{-sys.float_info.max:,.3f} MB/s" in window._io_metric.value_label.toolTip()
    window.update_sample(sample, (sample,))
    assert "disk vanished" not in window._status_label.toolTip()
    window.deleteLater()
