from __future__ import annotations

import sys
from pathlib import Path

from collectors.temperature import default_dll_path


def test_default_dll_path_uses_pyinstaller_meipass(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert default_dll_path() == tmp_path / "vendor" / "LibreHardwareMonitorLib.dll"
