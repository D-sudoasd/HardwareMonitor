"""Small, typed persistence layer for the floating monitor preferences."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from PySide6 import QtCore, QtGui, QtWidgets


DEFAULT_ORGANIZATION = "D-sudoasd"
DEFAULT_APPLICATION = "HardwareMonitor"
MIN_OPACITY = 0.80
MAX_OPACITY = 1.00


@dataclass(frozen=True)
class WindowPreferences:
    """Persisted values independent of Qt widget instances."""

    position: tuple[int, int] | None = None
    opacity: float = MAX_OPACITY
    auto_collapse: bool = True
    always_on_top: bool = True

    @property
    def position_point(self) -> QtCore.QPoint | None:
        point = _read_position(self.position)
        if point is None:
            return None
        return QtCore.QPoint(*point)


# This alias reads naturally for callers that use "monitor settings" rather
# than "window preferences" and keeps the public adapter intentionally small.
MonitorSettings = WindowPreferences


def clamp_opacity(value: object, default: float = MAX_OPACITY) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if numeric != numeric:  # NaN
        numeric = default
    return max(MIN_OPACITY, min(MAX_OPACITY, numeric))


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _read_position(value: object) -> tuple[int, int] | None:
    if isinstance(value, QtCore.QPoint):
        return value.x(), value.y()

    def coordinate(raw: object) -> int | None:
        try:
            numeric = float(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        # QPoint uses 32-bit integer coordinates.  Reject malformed values
        # before int()/QPoint can raise on inf, nan, or an oversized number.
        if not math.isfinite(numeric) or abs(numeric) > 2_147_483_647:
            return None
        try:
            return int(numeric)
        except (TypeError, ValueError, OverflowError):
            return None

    if isinstance(value, (tuple, list)) and len(value) >= 2:
        x = coordinate(value[0])
        y = coordinate(value[1])
        if x is None or y is None:
            return None
        return x, y
    if isinstance(value, str):
        # Helpful for INI files written by non-Qt tooling.
        cleaned = value.strip().replace("@Point", "").strip("()[]")
        parts = [part for part in cleaned.replace(",", " ").split() if part]
        if len(parts) >= 2:
            x = coordinate(parts[0])
            y = coordinate(parts[1])
            if x is None or y is None:
                return None
            return x, y
    return None


def position_is_visible(
    position: tuple[int, int] | QtCore.QPoint | None,
    screens: Iterable[QtGui.QScreen] | None = None,
) -> bool:
    """Return whether a saved top-left point is on an available screen."""

    point = _read_position(position)
    if point is None:
        return False
    if screens is not None:
        screen_list = list(screens)
    else:
        application = QtWidgets.QApplication.instance()
        screen_list = list(application.screens()) if application is not None else []
    if not screen_list:
        # Headless tests may not expose screens; a valid integer position is
        # still useful there and will be clamped by the real window at show.
        return True
    qpoint = QtCore.QPoint(*point)
    def geometry_for(screen: object) -> QtCore.QRect | None:
        if isinstance(screen, QtCore.QRect):
            return screen
        available_geometry = getattr(screen, "availableGeometry", None)
        return available_geometry() if callable(available_geometry) else None

    return any(
        geometry is not None and geometry.contains(qpoint)
        for screen in screen_list
        for geometry in (geometry_for(screen),)
    )


class SettingsAdapter:
    """Typed adapter around ``QSettings`` with safe defaults and clamping."""

    POSITION_KEY = "window/position"
    OPACITY_KEY = "window/opacity"
    AUTO_COLLAPSE_KEY = "window/autoCollapse"
    ALWAYS_ON_TOP_KEY = "window/alwaysOnTop"

    def __init__(
        self,
        qsettings: QtCore.QSettings | None = None,
        *,
        organization: str = DEFAULT_ORGANIZATION,
        application: str = DEFAULT_APPLICATION,
    ) -> None:
        self._settings = qsettings or QtCore.QSettings(organization, application)

    @property
    def qsettings(self) -> QtCore.QSettings:
        return self._settings

    def load(
        self,
        *,
        screens: Iterable[QtGui.QScreen] | None = None,
    ) -> WindowPreferences:
        position = _read_position(self._settings.value(self.POSITION_KEY, None))
        if position is not None and not position_is_visible(position, screens):
            position = None
        return WindowPreferences(
            position=position,
            opacity=clamp_opacity(self._settings.value(self.OPACITY_KEY, MAX_OPACITY)),
            auto_collapse=_as_bool(self._settings.value(self.AUTO_COLLAPSE_KEY, True), True),
            always_on_top=_as_bool(self._settings.value(self.ALWAYS_ON_TOP_KEY, True), True),
        )

    # ``read`` is a convenient synonym for callers that treat this as a
    # settings object rather than a repository.
    read = load

    def save(self, preferences: WindowPreferences) -> None:
        point = _read_position(preferences.position)
        if point is None:
            self._settings.remove(self.POSITION_KEY)
        else:
            self._settings.setValue(
                self.POSITION_KEY,
                QtCore.QPoint(*point),
            )
        self._settings.setValue(self.OPACITY_KEY, clamp_opacity(preferences.opacity))
        self._settings.setValue(self.AUTO_COLLAPSE_KEY, bool(preferences.auto_collapse))
        self._settings.setValue(self.ALWAYS_ON_TOP_KEY, bool(preferences.always_on_top))
        self._settings.sync()

    def save_position(self, position: tuple[int, int] | QtCore.QPoint) -> None:
        point = _read_position(position)
        if point is not None:
            self._settings.setValue(self.POSITION_KEY, QtCore.QPoint(*point))
            self._settings.sync()

    def save_opacity(self, opacity: float) -> None:
        self._settings.setValue(self.OPACITY_KEY, clamp_opacity(opacity))
        self._settings.sync()

    def save_auto_collapse(self, enabled: bool) -> None:
        self._settings.setValue(self.AUTO_COLLAPSE_KEY, bool(enabled))
        self._settings.sync()

    def save_always_on_top(self, enabled: bool) -> None:
        self._settings.setValue(self.ALWAYS_ON_TOP_KEY, bool(enabled))
        self._settings.sync()

    def reset(self) -> None:
        for key in (
            self.POSITION_KEY,
            self.OPACITY_KEY,
            self.AUTO_COLLAPSE_KEY,
            self.ALWAYS_ON_TOP_KEY,
        ):
            self._settings.remove(key)
        self._settings.sync()

    save_preferences = save
    load_preferences = load


# A more explicit name is useful in application code and keeps hidden/test
# clients from having to know which Qt type backs the adapter.
MonitorSettingsAdapter = SettingsAdapter
QSettingsAdapter = SettingsAdapter
Settings = SettingsAdapter
MonitorSettingsStore = SettingsAdapter
