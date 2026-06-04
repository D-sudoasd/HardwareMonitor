from __future__ import annotations

from datetime import datetime
from typing import Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from models.sample import HardwareSample


COLLAPSED_SIZE = QtCore.QSize(560, 38)
EXPANDED_SIZE = QtCore.QSize(560, 190)


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


def _compact_sensor_status(status: str) -> str:
    if status == "OK":
        return "Temp OK"
    normalized = status.lower()
    if "invalid" in normalized:
        return "Temp sensor invalid"
    if "cpu" in normalized and "disk" in normalized:
        return "Temp CPU/disk N/A"
    if "cpu" in normalized:
        return "Temp CPU N/A"
    if "disk" in normalized:
        return "Temp disk N/A"
    if len(status) > 42:
        return f"{status[:39]}..."
    return status


class MiniMetric(QtWidgets.QWidget):
    def __init__(self, title: str, accent: str, width: int, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = QtWidgets.QFrame()
        self._accent.setObjectName("metricAccent")
        self._accent.setStyleSheet(f"background: {accent}; border-radius: 2px;")
        self._title = QtWidgets.QLabel(title)
        self._title.setObjectName("miniTitle")
        self._value = QtWidgets.QLabel("N/A")
        self._value.setObjectName("miniValue")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self._accent)
        layout.addWidget(self._title)
        layout.addWidget(self._value)

        self._accent.setFixedSize(4, 18)
        self._title.setFixedWidth(34)
        self._value.setMinimumWidth(28)
        self.setFixedWidth(width)
        self.setFixedHeight(24)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class TrendChart(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(58)
        self.setMaximumHeight(68)
        self._history: tuple[HardwareSample, ...] = ()

    def set_history(self, history: Sequence[HardwareSample]) -> None:
        self._history = tuple(history)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QtGui.QPen(QtGui.QColor("#3c414a"), 1))
        painter.setBrush(QtGui.QColor("#15191f"))
        painter.drawRoundedRect(rect, 5, 5)

        if len(self._history) < 2:
            painter.setPen(QtGui.QColor("#8d96a3"))
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, "collecting")
            return

        self._draw_grid(painter, rect)
        self._draw_series(painter, rect, [s.cpu_percent for s in self._history], "#7dd3fc")
        self._draw_series(painter, rect, [s.memory_percent for s in self._history], "#a7f3d0")
        self._draw_series(painter, rect, [s.disk_active_percent for s in self._history], "#fbbf24")

    def _draw_grid(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        painter.setPen(QtGui.QPen(QtGui.QColor("#2b313a"), 1))
        for fraction in (0.5,):
            y = rect.top() + rect.height() * fraction
            painter.drawLine(rect.left() + 6, int(y), rect.right() - 6, int(y))

    def _draw_series(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        values: Sequence[float],
        color: str,
    ) -> None:
        if len(values) < 2:
            return

        chart = rect.adjusted(8, 8, -8, -8)
        path = QtGui.QPainterPath()
        x_step = chart.width() / max(1, len(values) - 1)
        for index, value in enumerate(values):
            clamped = max(0.0, min(100.0, float(value)))
            x = chart.left() + index * x_step
            y = chart.bottom() - (clamped / 100.0) * chart.height()
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QtGui.QPen(QtGui.QColor(color), 2))
        painter.drawPath(path)


class FloatingMonitor(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._drag_position: QtCore.QPoint | None = None
        self._press_global: QtCore.QPoint | None = None
        self._dragging = False
        self._expanded = False
        self._positioned = False
        self._last_sample: HardwareSample | None = None

        self.setWindowTitle("Hardware Floating Monitor")
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(1.0)

        self._cpu_metric = MiniMetric("CPU", "#7dd3fc", 78)
        self._memory_metric = MiniMetric("MEM", "#a7f3d0", 78)
        self._disk_metric = MiniMetric("DSK", "#fbbf24", 78)
        self._io_metric = MiniMetric("IO", "#f472b6", 112)
        self._temperature_metric = MiniMetric("TEMP", "#fb7185", 92)
        self._hint_label = QtWidgets.QLabel("click")
        self._hint_label.setObjectName("hintLabel")

        self._detail_line_1 = QtWidgets.QLabel("")
        self._detail_line_2 = QtWidgets.QLabel("")
        self._status_label = QtWidgets.QLabel("")
        self._chart = TrendChart()
        self._opacity_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(80, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.setFixedWidth(90)
        self._opacity_slider.valueChanged.connect(lambda value: self.setWindowOpacity(value / 100.0))
        self._close_button = QtWidgets.QPushButton("Close")
        self._close_button.clicked.connect(self.close)

        self._build_layout()
        self._apply_styles()
        self._set_expanded(False)

    @QtCore.Slot(object, object)
    def update_sample(self, sample: HardwareSample, history: Sequence[HardwareSample]) -> None:
        self._last_sample = sample
        self._cpu_metric.set_value(_format_percent_short(sample.cpu_percent))
        self._memory_metric.set_value(_format_percent_short(sample.memory_percent))
        self._disk_metric.set_value(_format_percent_short(sample.disk_usage_percent))
        self._io_metric.set_value(f"R{sample.disk_read_mb_s:.0f}/W{sample.disk_write_mb_s:.0f}")
        self._temperature_metric.set_value(_format_temp_short(sample.cpu_temp_c))

        self._detail_line_1.setText(
            "CPU {cpu}    MEM {used:.1f}/{total:.1f} GB ({mem})    DSK {disk}".format(
                cpu=_format_percent(sample.cpu_percent),
                used=sample.memory_used_gb,
                total=sample.memory_total_gb,
                mem=_format_percent(sample.memory_percent),
                disk=_format_percent(sample.disk_usage_percent),
            )
        )
        self._detail_line_2.setText(
            "IO R {read:.1f} / W {write:.1f} MB/s    Active {active:.1f}%    CPU {cpu_temp}    Disk {disk_temp}".format(
                read=sample.disk_read_mb_s,
                write=sample.disk_write_mb_s,
                active=sample.disk_active_percent,
                cpu_temp=_format_temp(sample.cpu_temp_c),
                disk_temp=_format_temp(sample.disk_temp_c),
            )
        )
        status = _compact_sensor_status(sample.sensor_status)
        self._status_label.setText(f"{status}    {datetime.fromtimestamp(sample.timestamp).strftime('%H:%M:%S')}")
        self._status_label.setToolTip(sample.sensor_status)
        self.setToolTip(sample.sensor_status)
        self._chart.set_history(history)

    def _build_layout(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._panel = QtWidgets.QFrame()
        self._panel.setObjectName("panel")
        root.addWidget(self._panel)

        layout = QtWidgets.QVBoxLayout(self._panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._mini_bar = QtWidgets.QFrame()
        self._mini_bar.setObjectName("miniBar")
        mini_layout = QtWidgets.QHBoxLayout(self._mini_bar)
        mini_layout.setContentsMargins(0, 0, 0, 0)
        mini_layout.setSpacing(8)
        mini_layout.addWidget(self._cpu_metric)
        mini_layout.addWidget(self._memory_metric)
        mini_layout.addWidget(self._disk_metric)
        mini_layout.addWidget(self._io_metric)
        mini_layout.addWidget(self._temperature_metric)
        mini_layout.addStretch(1)
        mini_layout.addWidget(self._hint_label)
        layout.addWidget(self._mini_bar)

        self._details = QtWidgets.QFrame()
        self._details.setObjectName("details")
        details_layout = QtWidgets.QVBoxLayout(self._details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(5)
        self._detail_line_1.setObjectName("detailText")
        self._detail_line_2.setObjectName("detailText")
        self._status_label.setObjectName("statusText")
        details_layout.addWidget(self._detail_line_1)
        details_layout.addWidget(self._detail_line_2)
        details_layout.addWidget(self._chart)

        footer = QtWidgets.QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self._status_label, 1)
        footer.addWidget(QtWidgets.QLabel("Opacity"))
        footer.addWidget(self._opacity_slider)
        footer.addWidget(self._close_button)
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
                font-size: 11px;
                font-weight: 700;
            }
            #miniValue {
                color: #f9fafb;
                font-size: 14px;
                font-weight: 800;
            }
            #hintLabel, #detailText, #statusText {
                color: #aab2bf;
                font-size: 11px;
            }
            QPushButton {
                background: #2a3038;
                border: 1px solid #3d4652;
                border-radius: 4px;
                color: #e5e7eb;
                padding: 3px 8px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #3a424d;
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

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._details.setVisible(expanded)
        self._hint_label.setText("hide" if expanded else "click")
        size = EXPANDED_SIZE if expanded else COLLAPSED_SIZE
        self.setFixedSize(size)

    def _toggle_expanded(self) -> None:
        self._set_expanded(not self._expanded)

    def _collapse_if_cursor_outside(self) -> None:
        if self._expanded and not self.underMouse():
            self._set_expanded(False)

    def _position_top_right(self) -> None:
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(available.right() - self.width() - 12, available.top() + 12)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._positioned:
            self._position_top_right()
            self._positioned = True

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        QtCore.QTimer.singleShot(200, self._collapse_if_cursor_outside)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        menu = QtWidgets.QMenu(self)
        toggle_action = menu.addAction("Collapse" if self._expanded else "Expand")
        close_action = menu.addAction("Close")
        selected = menu.exec(event.globalPos())
        if selected == toggle_action:
            self._toggle_expanded()
        elif selected == close_action:
            self.close()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_position = self._press_global - self.frameGeometry().topLeft()
            self._dragging = False
            event.accept()

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

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton and not self._dragging:
            self._toggle_expanded()
        self._drag_position = None
        self._press_global = None
        self._dragging = False
        event.accept()
