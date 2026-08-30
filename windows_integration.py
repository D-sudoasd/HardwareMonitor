"""Windows-only integration kept small and easy to test without elevation."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class ElevationCommand:
    executable: str
    arguments: tuple[str, ...]
    parameters: str
    working_directory: str
    verb: str = "runas"


@dataclass(frozen=True)
class ElevationResult:
    started: bool
    error_code: int | None = None
    message: str = ""


def build_elevation_command(
    executable: str | Path | None = None,
    arguments: Sequence[str] | None = None,
    *,
    working_directory: str | Path | None = None,
) -> ElevationCommand:
    """Build the exact ``ShellExecuteW`` inputs without launching anything."""

    if executable is None:
        executable = sys.executable
    executable_path = Path(executable)
    if arguments is None:
        if getattr(sys, "frozen", False):
            resolved_arguments: tuple[str, ...] = tuple(sys.argv[1:])
        else:
            # Source launches need to re-enter the application rather than
            # asking Python to execute this integration module as a script.
            resolved_arguments = (str(Path(__file__).with_name("main.py")), *sys.argv[1:])
    else:
        resolved_arguments = tuple(str(argument) for argument in arguments)

    cwd = Path(working_directory) if working_directory is not None else executable_path.parent
    return ElevationCommand(
        executable=str(executable_path),
        arguments=resolved_arguments,
        parameters=subprocess.list2cmdline(list(resolved_arguments)),
        working_directory=str(cwd),
    )


def restart_as_administrator(
    command: ElevationCommand | None = None,
) -> ElevationResult:
    """Request a UAC restart after an explicit user action.

    A failed or cancelled UAC request returns a result and leaves the current
    process untouched.  The caller decides whether to close after ``started``
    is true.
    """

    if os.name != "nt":
        return ElevationResult(False, message="Administrator restart is only available on Windows")

    command = command or build_elevation_command()
    try:
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        result = int(
            shell32.ShellExecuteW(
                None,
                command.verb,
                command.executable,
                command.parameters,
                command.working_directory,
                1,
            )
        )
    except Exception as exc:  # pragma: no cover - platform/API dependent.
        return ElevationResult(False, message=f"Could not request administrator restart: {exc}")

    if result > 32:
        return ElevationResult(True, message="Administrator process started")
    return ElevationResult(
        False,
        error_code=result,
        message=f"Administrator restart was not started (ShellExecuteW error {result})",
    )


# Descriptive alias for callers that do not want to imply that the app itself
# has already been elevated.
request_administrator_restart = restart_as_administrator
