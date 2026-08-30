"""Presentation-only floating monitor widget.

Collector health and freshness arrive as typed state from :mod:`app`; this
module never infers health by parsing diagnostic English text.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Callable, Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from models.sample import HardwareSample
from settings import SettingsAdapter, WindowPreferences, position_is_visible


COLLAPSED_SIZE = QtCore.QSize(800, 38)
EXPANDED_SIZE = QtCore.QSize(840, 250)
CPU_COLOR = "#7dd3fc"
MEMORY_COLOR = "#a7f3d0"
DISK_COLOR = "#fbbf24"
TREND_WINDOW_SECONDS = 10 * 60


def _format_percent(value: float) -> str:
    return f"{value:.1f}%"


def _format_percent_short(value: float) -> str:
    return f"{value:.0f}%"


def _format_temp(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f} C"


def _format_temp_short(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.0f}C"


def _format_io_rate_compact(value: float) -> str:
    """Keep the collapsed rate readable while preserving a full tooltip."""

    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return "N/A"
    if not math.isfinite(numeric):
        return "N/A"

    sign = "-" if numeric < 0 else ""
    scaled = abs(numeric)
    suffix = ""
    for candidate in ("", "G", "T", "P", "E"):
        suffix = candidate
        if scaled < 1024.0 or candidate == "E":
            break
        scaled /= 1024.0
    if scaled >= 100.0:
        number = f"{scaled:.0f}"
    elif scaled >= 10.0:
        number = f"{scaled:.1f}".rstrip("0").rstrip(".")
    else:
        number = f"{scaled:.2f}".rstrip("0").rstrip(".")
    compact = f"{sign}{number}{suffix}"
    if len(compact) <= 5:
        return compact

    # Extremely large finite values can still overflow the unit form (for
    # example 1e20 MB/s becomes a long integer with the E suffix).  Keep the
    # card token bounded; the full decimal value remains in the tooltip.
    for precision in (1, 0):
        scientific = f"{numeric:.{precision}e}".replace("+", "")
        if len(scientific) <= 5:
            return scientific
    return "-MAX" if numeric < 0 else "MAX"


def _format_io_tooltip(read: float, write: float) -> str:
    def format_rate(value: float) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            return "N/A"
        return f"{numeric:,.3f} MB/s" if math.isfinite(numeric) else "N/A"

    return f"IO ALL · Read {format_rate(read)} · Write {format_rate(write)}"


def _capacity_label(path: str) -> str:
    raw = (path or "C:").strip()
    cleaned = raw if raw in {"/", "\\"} else raw.rstrip("\\/")
    if not cleaned:
        cleaned = "C:"
    if len(cleaned) == 1 and cleaned.isalpha():
        cleaned += ":"
    return f"SYS {cleaned}"


def _format_sensor_state(sample: HardwareSample) -> str:
    """Format a compact state from structured fields, not message matching."""

    if sample.sensor_available:
        return "Temp OK"
    if sample.cpu_temp_c is None and sample.disk_temp_c is None:
        return "Temp N/A"
    if sample.cpu_temp_c is None:
        return "Temp CPU N/A"
    if sample.disk_temp_c is None:
        return "Temp disk N/A"
    return "Temp unavailable"


class MiniMetric(QtWidgets.QWidget):
    def __init__(
        self,
        title: str,
        accent: str,
        width: int,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._accent = QtWidgets.QFrame()
        self._accent.setObjectName("metricAccent")
        self._accent.setStyleSheet(f"background: {accent}; border-radius: 2px;")
        self._title = QtWidgets.QLabel(title)
        self._title.setObjectName("miniTitle")
        self._value = QtWidgets.QLabel("N/A")
        self._value.setObjectName("miniValue")
        title_font = QtGui.QFont("Segoe UI")
        title_font.setPixelSize(10)
        title_font.setBold(True)
        self._title.setFont(title_font)
        value_font = QtGui.QFont("Consolas")
        value_font.setPixelSize(12)
        value_font.setBold(True)
        self._value.setFont(value_font)
        self._value.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._value.setSizePolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding, QtWidgets.QSizePolicy.Policy.Preferred)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self._accent)
        layout.addWidget(self._title)
        layout.addWidget(self._value, 1)

        self._accent.setFixedSize(4, 18)
        self._title.setMinimumWidth(max(30, self._title.fontMetrics().horizontalAdvance(title)))
        # Reserve enough room for the largest compact IO value expected from a
        # normal desktop.  The label can still expand instead of clipping.
        reserve_text = "R130/W42" if title.upper().startswith("IO") else "100%"
        minimum_value_width = self._value.fontMetrics().horizontalAdvance(reserve_text) + 4
        self._value.setMinimumWidth(minimum_value_width)
        self.setMinimumWidth(max(int(width), self.sizeHint().width()))
        self.setMinimumHeight(24)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{title} metric")
        self.setToolTip(title)
        self._title.setToolTip(title)

    @property
    def value_label(self) -> QtWidgets.QLabel:
        return self._value

    def set_title(self, title: str) -> None:
        self._title.setText(title)
        self._title.setMinimumWidth(max(30, self._title.fontMetrics().horizontalAdvance(title)))
        self.setAccessibleName(f"{title} metric")
        self.setToolTip(title)
        self._title.setToolTip(title)

    def set_value(self, value: str) -> None:
        self._value.setText(value)
        self._value.adjustSize()
        self.updateGeometry()


class TrendChart(QtWidgets.QWidget):
    """Small percent-only trend plot with explicit legend and time basis."""

    LEGEND = (
        ("CPU", CPU_COLOR),
        ("MEM", MEMORY_COLOR),
        ("DISK ACTIVE", DISK_COLOR),
    )

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(84)
        self.setMaximumHeight(96)
        self.setAccessibleName("Ten minute CPU, memory, and disk activity trend")
        self.setAccessibleDescription(
            "Legend: CPU, MEM, DISK ACTIVE. Percent scale: 0%, 50%, 100%. Time: 10 min to now."
        )
        self.setToolTip("Percent scale: 0% to 100%; time basis: 10 min to now")
        self._history: tuple[HardwareSample, ...] = ()

    @property
    def history(self) -> tuple[HardwareSample, ...]:
        return self._history

    @property
    def legend(self) -> tuple[str, ...]:
        return tuple(label for label, _ in self.LEGEND)

    @property
    def time_labels(self) -> tuple[str, str]:
        return ("10 min", "now")

    def set_history(self, history: Sequence[HardwareSample]) -> None:
        # SampleHistory already keeps this order, but sorting at the view
        # boundary also protects direct callers from a wall-clock rollback.
        self._history = tuple(sorted(history, key=lambda sample: float(sample.timestamp)))
        self.update()

    @staticmethod
    def _timestamp_xs(samples: Sequence[HardwareSample], left: float, right: float) -> list[float]:
        ordered_samples = tuple(sorted(samples, key=lambda sample: float(sample.timestamp)))
        if not ordered_samples:
            return []
        latest = float(ordered_samples[-1].timestamp)
        window_start = latest - TREND_WINDOW_SECONDS
        return [
            left
            + max(
                0.0,
                min(
                    1.0,
                    (float(sample.timestamp) - window_start) / TREND_WINDOW_SECONDS,
                ),
            )
            * (right - left)
            for sample in ordered_samples
        ]

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QtGui.QPen(QtGui.QColor("#3c414a"), 1))
        painter.setBrush(QtGui.QColor("#15191f"))
        painter.drawRoundedRect(rect, 5, 5)

        self._draw_legend(painter, rect)
        chart = rect.adjusted(33, 21, -9, -18)
        self._draw_grid(painter, chart)
        self._draw_axis_labels(painter, rect, chart)
        if len(self._history) < 2:
            painter.setPen(QtGui.QColor("#8d96a3"))
            painter.drawText(chart, QtCore.Qt.AlignmentFlag.AlignCenter, "collecting")
            return

        self._draw_series(painter, chart, self._history, lambda sample: sample.cpu_percent, CPU_COLOR)
        self._draw_series(painter, chart, self._history, lambda sample: sample.memory_percent, MEMORY_COLOR)
        self._draw_series(painter, chart, self._history, lambda sample: sample.disk_active_percent, DISK_COLOR)

    def _draw_legend(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        x = rect.left() + 9
        y = rect.top() + 14
        painter.setFont(QtGui.QFont("Segoe UI", 8))
        for label, color in self.LEGEND:
            painter.setPen(QtGui.QPen(QtGui.QColor(color), 2))
            painter.drawLine(x, y - 3, x + 9, y - 3)
            painter.setPen(QtGui.QColor("#b5bdc9"))
            painter.drawText(x + 13, y, label)
            x += 66 if label != "DISK ACTIVE" else 90

    @staticmethod
    def _draw_grid(painter: QtGui.QPainter, chart: QtCore.QRect) -> None:
        painter.setPen(QtGui.QPen(QtGui.QColor("#2b313a"), 1))
        for fraction in (0.0, 0.5, 1.0):
            y = chart.top() + chart.height() * fraction
            painter.drawLine(chart.left(), int(y), chart.right(), int(y))

    @staticmethod
    def _draw_axis_labels(painter: QtGui.QPainter, rect: QtCore.QRect, chart: QtCore.QRect) -> None:
        painter.setFont(QtGui.QFont("Segoe UI", 8))
        painter.setPen(QtGui.QColor("#8d96a3"))
        for label, fraction in (("100%", 0.0), ("50%", 0.5), ("0%", 1.0)):
            y = int(chart.top() + chart.height() * fraction)
            painter.drawText(rect.left() + 4, y + 3, label)
        painter.drawText(chart.left(), rect.bottom() - 4, "10 min")
        painter.drawText(chart.right() - 25, rect.bottom() - 4, "now")

    def _draw_series(
        self,
        painter: QtGui.QPainter,
        chart: QtCore.QRect,
        samples: Sequence[HardwareSample],
        accessor: Callable[[HardwareSample], float],
        color: str,
    ) -> None:
        if len(samples) < 2:
            return
        ordered_samples = tuple(sorted(samples, key=lambda sample: float(sample.timestamp)))
        path = QtGui.QPainterPath()
        x_values = self._timestamp_xs(ordered_samples, chart.left(), chart.right())
        for index, sample in enumerate(ordered_samples):
            value = max(0.0, min(100.0, float(accessor(sample))))
            y = chart.bottom() - (value / 100.0) * chart.height()
            x = x_values[index]
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QtGui.QPen(QtGui.QColor(color), 2))
        painter.drawPath(path)


class FloatingMonitor(QtWidgets.QWidget):
    quit_requested = QtCore.Signal()
    restart_as_admin_requested = QtCore.Signal()
    hide_requested = QtCore.Signal()

    def __init__(
        self,
        *,
        settings: SettingsAdapter | None = None,
        tray_available: bool = False,
    ) -> None:
        super().__init__()
        self._settings = settings or SettingsAdapter()
        self._drag_position: QtCore.QPoint | None = None
        self._press_global: QtCore.QPoint | None = None
        self._dragging = False
        self._expanded = False
        self._positioned = False
        self._last_sample: HardwareSample | None = None
        self._tray_available = bool(tray_available)
        self._allow_close = False
        self._shutdown_pending = False
        self._status_state: object | None = None
        self._preferences = self._settings.load()
        self._auto_collapse = self._preferences.auto_collapse
        self._always_on_top = self._preferences.always_on_top

        self.setWindowTitle("Hardware Floating Monitor")
        self.setAccessibleName("Hardware Floating Monitor")
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._apply_window_flags()
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(self._preferences.opacity)

        self._cpu_metric = MiniMetric("CPU", CPU_COLOR, 72, self)
        self._memory_metric = MiniMetric("MEM", MEMORY_COLOR, 78, self)
        self._disk_metric = MiniMetric("SYS C:", DISK_COLOR, 92, self)
        self._io_metric = MiniMetric("IO ALL", "#f472b6", 210, self)
        self._temperature_metric = MiniMetric("TEMP", "#fb7185", 92, self)
        self._hint_label = QtWidgets.QLabel("Enter")
        self._hint_label.setObjectName("hintLabel")
        self._hint_label.setAccessibleName("Expand or collapse hint")
        self._hint_label.setToolTip("Press Enter or Space to expand/collapse")
        self._hint_label.setFixedWidth(40)

        self._health_label = QtWidgets.QLabel("START")
        self._health_label.setObjectName("healthText")
        self._health_label.setAccessibleName("Telemetry freshness")
        self._health_label.setFixedWidth(50)

        self._detail_line_1 = QtWidgets.QLabel("")
        self._detail_line_2 = QtWidgets.QLabel("")
        self._status_label = QtWidgets.QLabel("Starting…")
        self._chart = TrendChart(self)
        self._opacity_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        self._opacity_slider.setRange(80, 100)
        self._opacity_slider.setValue(round(self._preferences.opacity * 100))
        self._opacity_slider.setFixedWidth(90)
        self._opacity_slider.setAccessibleName("Window opacity")
        self._opacity_slider.setToolTip("Window opacity, 80 to 100 percent")
        self._opacity_slider.valueChanged.connect(self._opacity_changed)
        self._auto_collapse_checkbox = QtWidgets.QCheckBox("Auto-collapse", self)
        self._auto_collapse_checkbox.setChecked(self._auto_collapse)
        self._auto_collapse_checkbox.setAccessibleName("Automatically collapse when pointer leaves")
        self._auto_collapse_checkbox.toggled.connect(self._auto_collapse_changed)
        self._pin_checkbox = QtWidgets.QCheckBox("Pin", self)
        self._pin_checkbox.setChecked(self._always_on_top)
        self._pin_checkbox.setAccessibleName("Keep monitor always on top")
        self._pin_checkbox.toggled.connect(self._pin_changed)
        self._menu_button = QtWidgets.QPushButton("Menu", self)
        self._menu_button.setAccessibleName("Monitor actions menu")
        self._menu_button.setToolTip("Expand, reset position, hide, quit, or restart as administrator")
        self._menu_button.clicked.connect(self._show_menu)
        self._hide_button = QtWidgets.QPushButton("Hide", self)
        self._hide_button.setAccessibleName("Hide monitor")
        self._hide_button.clicked.connect(self.request_hide)

        self._build_layout()
        self._apply_styles()
        self._set_expanded(False)
        self.set_tray_available(self._tray_available)

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def last_sample(self) -> HardwareSample | None:
        return self._last_sample

    @property
    def chart(self) -> TrendChart:
        return self._chart

    def set_starting(self) -> None:
        self._health_label.setText("START")
        self._status_label.setText("Starting…")
        self._status_label.setToolTip("Waiting for the first telemetry sample")

    @QtCore.Slot(object, object)
    def update_sample(self, sample: HardwareSample, history: Sequence[HardwareSample]) -> None:
        self._last_sample = sample
        self._disk_metric.set_title(_capacity_label(sample.disk_capacity_path))
        self._cpu_metric.set_value(_format_percent_short(sample.cpu_percent))
        self._memory_metric.set_value(_format_percent_short(sample.memory_percent))
        self._disk_metric.set_value(_format_percent_short(sample.disk_usage_percent))
        compact_read = _format_io_rate_compact(sample.disk_read_mb_s)
        compact_write = _format_io_rate_compact(sample.disk_write_mb_s)
        self._io_metric.set_value(f"R{compact_read}/W{compact_write}")
        io_tooltip = _format_io_tooltip(sample.disk_read_mb_s, sample.disk_write_mb_s)
        self._io_metric.setToolTip(io_tooltip)
        self._io_metric.value_label.setToolTip(io_tooltip)
        self._temperature_metric.set_value(_format_temp_short(sample.cpu_temp_c))

        capacity = _capacity_label(sample.disk_capacity_path)
        io_scope = sample.disk_io_scope or "all disks"
        self._detail_line_1.setText(
            "CPU {cpu}    MEM {used:.1f}/{total:.1f} GB ({mem})    {capacity} {disk}".format(
                cpu=_format_percent(sample.cpu_percent),
                used=sample.memory_used_gb,
                total=sample.memory_total_gb,
                mem=_format_percent(sample.memory_percent),
                capacity=capacity,
                disk=_format_percent(sample.disk_usage_percent),
            )
        )
        self._detail_line_2.setText(
            "IO {scope}  Read {read:.1f} / Write {write:.1f} MB/s    Active {active:.1f}%    CPU {cpu_temp}    Disk {disk_temp}".format(
                scope=io_scope,
                read=sample.disk_read_mb_s,
                write=sample.disk_write_mb_s,
                active=sample.disk_active_percent,
                cpu_temp=_format_temp(sample.cpu_temp_c),
                disk_temp=_format_temp(sample.disk_temp_c),
            )
        )
        self._chart.set_history(history)
        self._health_label.setText("OK" if sample.sensor_available else "TEMP")
        self._health_label.setToolTip(sample.sensor_message or sample.sensor_status)
        self.setToolTip(sample.sensor_message or sample.sensor_status)
        self._status_label.setToolTip(sample.sensor_message or sample.sensor_status)
        self.update_status_from_sample(sample)

    def update_status_from_sample(self, sample: HardwareSample) -> None:
        stamp = datetime.fromtimestamp(sample.timestamp).strftime("%H:%M:%S")
        self._status_label.setText(f"Updated {stamp} · {_format_sensor_state(sample)}")

    @QtCore.Slot(object)
    def update_status(self, status: object) -> None:
        """Consume ``TelemetryStatus`` structurally without string inference."""

        self._status_state = status
        phase = getattr(status, "phase", "")
        message = getattr(status, "message", "")
        if phase == "starting":
            self.set_starting()
            return
        if phase == "stale":
            self._health_label.setText("STALE")
            self._status_label.setText(message or "Update failed — showing last sample")
            failure = getattr(status, "failure", None)
            failure_message = getattr(failure, "message", "")
            self._status_label.setToolTip(failure_message)
            self._health_label.setToolTip(failure_message)
            self.setToolTip(failure_message)
            return
        if phase == "error":
            self._health_label.setText("ERROR")
            self._status_label.setText(message or "Update failed — retrying")
            failure = getattr(status, "failure", None)
            failure_message = getattr(failure, "message", "")
            self._status_label.setToolTip(failure_message)
            self._health_label.setToolTip(failure_message)
            self.setToolTip(failure_message)
            return
        if phase == "updated" and message:
            sensor = _format_sensor_state(self._last_sample) if self._last_sample is not None else ""
            self._health_label.setText("OK" if self._last_sample and self._last_sample.sensor_available else "TEMP")
            self._status_label.setText(f"{message} · {sensor}".rstrip(" ·"))

    @QtCore.Slot(object)
    def update_state(self, state: object) -> None:
        sample = getattr(state, "sample", None)
        history = getattr(state, "history", ())
        status = getattr(state, "status", None)
        if sample is not None:
            self.update_sample(sample, history)
        if status is not None:
            self.update_status(status)

    def _build_layout(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._panel = QtWidgets.QFrame(self)
        self._panel.setObjectName("panel")
        root.addWidget(self._panel)

        layout = QtWidgets.QVBoxLayout(self._panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._mini_bar = QtWidgets.QFrame(self._panel)
        self._mini_bar.setObjectName("miniBar")
        mini_layout = QtWidgets.QHBoxLayout(self._mini_bar)
        mini_layout.setContentsMargins(0, 0, 0, 0)
        mini_layout.setSpacing(7)
        for metric in (
            self._cpu_metric,
            self._memory_metric,
            self._disk_metric,
            self._io_metric,
            self._temperature_metric,
        ):
            mini_layout.addWidget(metric)
        mini_layout.addWidget(self._health_label)
        mini_layout.addStretch(1)
        mini_layout.addWidget(self._hint_label)
        layout.addWidget(self._mini_bar)

        self._details = QtWidgets.QFrame(self._panel)
        self._details.setObjectName("details")
        details_layout = QtWidgets.QVBoxLayout(self._details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(5)
        self._detail_line_1.setObjectName("detailText")
        self._detail_line_2.setObjectName("detailText")
        self._status_label.setObjectName("statusText")
        self._detail_line_1.setAccessibleName("CPU memory and capacity details")
        self._detail_line_2.setAccessibleName("Disk IO and temperature details")
        for detail_line in (self._detail_line_1, self._detail_line_2):
            detail_line.setWordWrap(True)
            detail_line.setMinimumWidth(0)
            detail_line.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred,
            )
        details_layout.addWidget(self._detail_line_1)
        details_layout.addWidget(self._detail_line_2)
        details_layout.addWidget(self._chart)

        self._status_label.setWordWrap(True)
        self._status_label.setMinimumWidth(0)
        self._status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        status_row = QtWidgets.QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self._status_label, 1)
        details_layout.addLayout(status_row)

        footer = QtWidgets.QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        opacity_label = QtWidgets.QLabel("Opacity", self)
        opacity_label.setAccessibleName("Opacity setting")
        footer.addWidget(opacity_label)
        footer.addWidget(self._opacity_slider)
        footer.addWidget(self._auto_collapse_checkbox)
        footer.addWidget(self._pin_checkbox)
        footer.addWidget(self._menu_button)
        footer.addWidget(self._hide_button)
        details_layout.addLayout(footer)
        layout.addWidget(self._details)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                color: #e5e7eb;
                font-family: Segoe UI, Microsoft YaHei, Arial;
                font-size: 12px;
            }
            #panel {
                background: rgba(14, 17, 22, 252);
                border: 1px solid #343b45;
                border-radius: 7px;
            }
            #miniTitle {
                color: #9ca3af;
                font-size: 10px;
                font-weight: 700;
            }
            #miniValue {
                color: #f9fafb;
                font-family: Consolas, Cascadia Mono, monospace;
                font-size: 10px;
                font-weight: 800;
            }
            #hintLabel, #detailText, #statusText, #healthText {
                color: #aab2bf;
                font-size: 11px;
            }
            #healthText {
                color: #fbbf24;
                font-weight: 700;
            }
            QPushButton, QCheckBox {
                color: #e5e7eb;
            }
            QPushButton {
                background: #2a3038;
                border: 1px solid #3d4652;
                border-radius: 4px;
                color: #e5e7eb;
                padding: 3px 8px;
                font-weight: 700;
            }
            QPushButton:hover, QPushButton:focus {
                background: #3a424d;
                border-color: #7dd3fc;
            }
            QCheckBox:focus, QSlider:focus {
                outline: 1px solid #7dd3fc;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #343b45;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #e5e7eb;
                width: 10px;
                margin: -4px 0;
                border-radius: 5px;
            }
            """
        )

    def _apply_window_flags(self) -> None:
        flags = QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Tool
        if self._always_on_top:
            flags |= QtCore.Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._details.setVisible(self._expanded)
        self._hint_label.setText("Escape" if self._expanded else "Enter")
        self._hint_label.setToolTip("Press Escape to collapse" if self._expanded else "Press Enter or Space to expand")
        size = EXPANDED_SIZE if self._expanded else COLLAPSED_SIZE
        self.setFixedSize(size)

    def _toggle_expanded(self) -> None:
        self._set_expanded(not self._expanded)

    def _collapse_if_cursor_outside(self) -> None:
        if self._auto_collapse and self._expanded and not self.underMouse():
            self._set_expanded(False)

    def _position_top_right(self) -> None:
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(available.right() - self.width() - 12, available.top() + 12)

    def _restore_position(self) -> None:
        position = self._preferences.position
        if position is not None and position_is_visible(position):
            self.move(QtCore.QPoint(*position))
        else:
            self._position_top_right()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._positioned:
            self._restore_position()
            self._positioned = True

    def moveEvent(self, event: QtGui.QMoveEvent) -> None:
        super().moveEvent(event)
        if self._positioned:
            self._settings.save_position(self.pos())

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        QtCore.QTimer.singleShot(200, self._collapse_if_cursor_outside)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        self._show_menu(event.globalPos())

    def _show_menu(self, position: QtCore.QPoint | None = None) -> None:
        menu = QtWidgets.QMenu(self)
        menu.setAccessibleName("Hardware monitor actions")
        toggle_action = menu.addAction("Collapse" if self._expanded else "Expand")
        toggle_action.setShortcut(QtGui.QKeySequence("Enter"))
        menu.addAction("Reset position", self.reset_position)
        auto_action = menu.addAction("Auto-collapse when pointer leaves")
        auto_action.setCheckable(True)
        auto_action.setChecked(self._auto_collapse)
        auto_action.toggled.connect(self._auto_collapse_changed)
        pin_action = menu.addAction("Pin always on top")
        pin_action.setCheckable(True)
        pin_action.setChecked(self._always_on_top)
        pin_action.toggled.connect(self._pin_changed)
        menu.addSeparator()
        hide_label = "Hide" if self._tray_available else "Quit (no tray available)"
        menu.addAction(hide_label, self.request_hide)
        menu.addAction("Restart as administrator", self.request_restart_as_admin)
        menu.addAction("Quit", self.request_quit)
        selected = menu.exec(position or self.mapToGlobal(self.rect().center()))
        if selected == toggle_action:
            self._toggle_expanded()

    def reset_position(self) -> None:
        self._preferences = WindowPreferences(
            position=None,
            opacity=self.windowOpacity(),
            auto_collapse=self._auto_collapse,
            always_on_top=self._always_on_top,
        )
        self._settings.save(self._preferences)
        self._position_top_right()
        self._settings.save_position(self.pos())

    def _opacity_changed(self, value: int) -> None:
        opacity = max(0.8, min(1.0, int(value) / 100.0))
        self.setWindowOpacity(opacity)
        self._settings.save_opacity(opacity)

    def _auto_collapse_changed(self, enabled: bool) -> None:
        self._auto_collapse = bool(enabled)
        self._auto_collapse_checkbox.blockSignals(True)
        self._auto_collapse_checkbox.setChecked(self._auto_collapse)
        self._auto_collapse_checkbox.blockSignals(False)
        self._settings.save_auto_collapse(self._auto_collapse)

    def _pin_changed(self, enabled: bool) -> None:
        self._always_on_top = bool(enabled)
        self._pin_checkbox.blockSignals(True)
        self._pin_checkbox.setChecked(self._always_on_top)
        self._pin_checkbox.blockSignals(False)
        self._settings.save_always_on_top(self._always_on_top)
        was_visible = self.isVisible()
        self._apply_window_flags()
        if was_visible:
            self.show()

    def set_tray_available(self, available: bool) -> None:
        self._tray_available = bool(available)
        if hasattr(self, "_hide_button"):
            label = "Hide" if self._tray_available else "Quit (no tray available)"
            self._hide_button.setText(label)
            self._hide_button.setAccessibleName("Hide monitor" if self._tray_available else label)
            self._hide_button.setToolTip(
                "Hide to the system tray" if self._tray_available else "Quit because no system tray is available"
            )

    def show_from_tray(self) -> None:
        self._allow_close = False
        self.show()
        self.raise_()
        self.activateWindow()

    def request_hide(self) -> None:
        if not self._tray_available:
            # Without a tray there is no reliable recovery path for a hidden
            # process, so Hide degrades to a normal quit.
            self.request_quit()
            return
        self.hide_requested.emit()
        self.hide()

    def request_restart_as_admin(self) -> None:
        self.restart_as_admin_requested.emit()

    def request_quit(self) -> None:
        self._allow_close = True
        self.quit_requested.emit()
        self.close()

    def show_shutdown_pending(self) -> None:
        """Keep a visible recovery surface while a native call is unwinding."""

        self._shutdown_pending = True
        self._allow_close = False
        self._health_label.setText("WAIT")
        self._status_label.setText("Waiting for collector to return…")
        self._status_label.setToolTip("Shutdown is waiting for a native collector call to return")
        self.setToolTip("Shutdown is waiting for a native collector call to return")
        self._hide_button.setEnabled(False)
        self.show()
        self.raise_()

    def finish_quit(self) -> None:
        self._shutdown_pending = False
        self._allow_close = True
        self._hide_button.setEnabled(True)
        self.close()

    def save_settings(self) -> None:
        self._settings.save(
            WindowPreferences(
                position=(self.pos().x(), self.pos().y()) if self._positioned else self._preferences.position,
                opacity=self.windowOpacity(),
                auto_collapse=self._auto_collapse,
                always_on_top=self._always_on_top,
            )
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.save_settings()
        if self._shutdown_pending:
            self.show()
            event.ignore()
            return
        if self._tray_available and not self._allow_close:
            self.hide()
            event.ignore()
            return
        if not self._allow_close:
            self.quit_requested.emit()
            # The coordinator may have discovered a blocking native call
            # synchronously during emit and switched the window to WAIT.
            if self._shutdown_pending:
                self.show()
                event.ignore()
                return
        event.accept()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter, QtCore.Qt.Key.Key_Space):
            self._toggle_expanded()
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Escape:
            if self._expanded:
                self._set_expanded(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_position = self._press_global - self.frameGeometry().topLeft()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_position is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            if self._press_global is not None:
                distance = (current - self._press_global).manhattanLength()
                if distance >= QtWidgets.QApplication.startDragDistance():
                    self._dragging = True
            if self._dragging:
                self.move(current - self._drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton and not self._dragging:
            self._toggle_expanded()
        self._drag_position = None
        self._press_global = None
        self._dragging = False
        event.accept()
