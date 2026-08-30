from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

from settings import SettingsAdapter, WindowPreferences, position_is_visible
import windows_integration
from windows_integration import build_elevation_command, restart_as_administrator


class FakeScreen:
    def __init__(self, geometry: QtCore.QRect) -> None:
        self._geometry = geometry

    def availableGeometry(self) -> QtCore.QRect:
        return self._geometry


def test_qsettings_round_trip_clamps_values_and_rejects_offscreen_position(tmp_path: Path) -> None:
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(["hardware-monitor-settings-tests"])
    ini_path = tmp_path / "settings.ini"
    qsettings = QtCore.QSettings(str(ini_path), QtCore.QSettings.Format.IniFormat)
    adapter = SettingsAdapter(qsettings)
    screen = FakeScreen(QtCore.QRect(0, 0, 1920, 1080))

    adapter.save(WindowPreferences((120, 240), 1.5, auto_collapse=False, always_on_top=False))
    loaded = adapter.load(screens=[screen])
    assert loaded.position == (120, 240)
    assert loaded.opacity == 1.0
    assert loaded.auto_collapse is False
    assert loaded.always_on_top is False

    adapter.save_position((5000, 5000))
    assert adapter.load(screens=[screen]).position is None
    for malformed in ("(inf, 1)", "(nan, 1)", "(999999999999999999999, 1)"):
        qsettings.setValue(adapter.POSITION_KEY, malformed)
        assert adapter.load(screens=[screen]).position is None
    assert position_is_visible((1, 1), [screen])
    assert not position_is_visible((5000, 5000), [screen])


def test_elevation_command_is_pure_and_quotes_arguments() -> None:
    command = build_elevation_command(
        Path(r"C:\Tools\HardwareMonitor.exe"),
        ["--profile", "lab profile"],
        working_directory=r"C:\Tools",
    )

    assert command.verb == "runas"
    assert command.executable.endswith("HardwareMonitor.exe")
    assert command.arguments == ("--profile", "lab profile")
    assert "lab profile" in command.parameters
    assert command.working_directory.endswith("C:\\Tools")


def test_non_windows_elevation_request_is_a_recoverable_result(monkeypatch) -> None:
    # Replace the module binding rather than mutating the process-wide os.name;
    # pathlib and pytest also rely on the latter remaining the host value.
    monkeypatch.setattr(windows_integration, "os", SimpleNamespace(name="posix"))
    result = restart_as_administrator(build_elevation_command("monitor.exe", []))

    assert result.started is False
    assert "only available" in result.message
