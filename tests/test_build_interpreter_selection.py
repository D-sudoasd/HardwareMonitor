from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_probe_skips_broken_windowsapps_python_alias() -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    assert powershell is not None, "PowerShell is required for the offline build probe"
    command = [
        powershell,
        "-NoProfile",
        "-File",
        str(PROJECT_ROOT / "scripts" / "build_exe.ps1"),
        "-ProbeOnly",
    ]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=os.environ.copy(),
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    assert "selected_python=" in output
    selected_line = next(line for line in output.splitlines() if line.startswith("selected_python="))
    assert "WindowsApps\\python.exe" not in selected_line
    version_line = next(line for line in output.splitlines() if line.startswith("selected_python_version="))
    version_parts = tuple(int(part) for part in version_line.split("=", 1)[1].split("."))
    assert version_parts >= (3, 11)


@pytest.mark.parametrize("response_shape", ("request_message", "response_uri", "location"))
def test_release_tag_probe_accepts_offline_response_shapes(response_shape: str) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    assert powershell is not None, "PowerShell is required for the offline release-tag probe"

    tag_uri = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/tag/v1.2.3"
    if response_shape == "request_message":
        response = (
            "[pscustomobject]@{ BaseResponse = [pscustomobject]@{ "
            f"RequestMessage = [pscustomobject]@{{ RequestUri = [uri]'{tag_uri}' }} "
            "}; Headers = [pscustomobject]@{} }"
        )
    elif response_shape == "response_uri":
        response = (
            "[pscustomobject]@{ BaseResponse = [pscustomobject]@{ "
            f"ResponseUri = [uri]'{tag_uri}' "
            "}; Headers = [pscustomobject]@{} }"
        )
    else:
        response = (
            "[pscustomobject]@{ Headers = [pscustomobject]@{ "
            "Location = '/LibreHardwareMonitor/LibreHardwareMonitor/releases/tag/v1.2.3' "
            "} }"
        )

    script_path = str(PROJECT_ROOT / "scripts" / "build_exe.ps1").replace("'", "''")
    command_text = f"""
$ErrorActionPreference = 'Stop'
function Invoke-WebRequest {{
    param([string]$Uri, [switch]$UseBasicParsing)
    return {response}
}}
. '{script_path}' -ProbeOnly
$tag = Get-LibreHardwareMonitorTag
if ($tag -ne 'v1.2.3') {{ throw "Unexpected tag: $tag" }}
Write-Output "tag=$tag"
"""
    result = subprocess.run(
        [powershell, "-NoProfile", "-Command", command_text],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=os.environ.copy(),
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    assert "tag=v1.2.3" in output
