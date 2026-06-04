# HardwareMonitor

HardwareMonitor is a low-obstruction Windows desktop micro-bar for watching CPU, memory, disk usage, disk I/O, and hardware temperature status while you work.

It is designed for people who want live system telemetry without a large dashboard covering documents, terminals, plots, or lab-control software.

![HardwareMonitor preview](docs/preview.svg)

## Highlights

- Always-on-top Windows micro-bar, default height about 38 px.
- One-line live metrics: CPU, memory, disk usage, disk read/write, and temperature status.
- Click to expand a compact trend panel with a 10-minute in-memory history.
- Uses `psutil` for CPU, memory, and disk metrics.
- Uses LibreHardwareMonitor through `pythonnet` for CPU and disk temperature sensors.
- Shows `N/A` when a hardware sensor is unavailable or returns invalid values. It does not fabricate temperatures.
- Portable release ZIP. No Python installation is needed for release users.

## Download

Download the latest release:

https://github.com/D-sudoasd/HardwareMonitor/releases/latest

Use the packaged build:

1. Download `HardwareMonitor.zip`.
2. Extract it anywhere.
3. Run `HardwareMonitor.exe`.
4. Allow the Windows administrator prompt if you want the best chance of reading hardware temperature sensors.

The app still works for CPU, memory, disk usage, and disk I/O if temperature sensors are unavailable.

## Usage

- Drag the micro-bar to reposition it.
- Left-click the bar to expand or collapse details.
- Move the cursor away from the expanded panel to fold it back into the micro-bar.
- Right-click for a small menu with expand/collapse and close actions.

## Temperature Notes

Temperature readings depend on motherboard firmware, CPU/SSD controller support, Windows permissions, and LibreHardwareMonitor support.

If HardwareMonitor shows `TEMP N/A` or `Temp sensor invalid`:

- Run the app as Administrator.
- Compare with the LibreHardwareMonitor GUI or HWiNFO.
- Treat unavailable sensors as an environment limitation, not as a normal temperature.

On some systems a sensor may exist but return `0.0 C`; HardwareMonitor intentionally rejects that value as invalid.

## Build From Source

Requirements:

- Windows
- Python 3.11+
- PowerShell

Install and run from source:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python main.py
```

Build the portable EXE and ZIP:

```powershell
.\scripts\build_exe.ps1
```

The build script downloads LibreHardwareMonitor from the official GitHub release, vendors the required DLLs and license files into the build, runs tests, and writes:

```text
dist\HardwareMonitor\HardwareMonitor.exe
dist\HardwareMonitor.zip
dist\HardwareMonitor.zip.sha256
```

## Verify Release ZIP

```powershell
Get-FileHash -Algorithm SHA256 .\HardwareMonitor.zip
Get-Content .\HardwareMonitor.zip.sha256
```

The two hashes should match.

## Development Checks

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m py_compile main.py app.py collectors\system_metrics.py collectors\temperature.py models\sample.py ui\floating_monitor.py
```

## Third-Party Components

Packaged releases include LibreHardwareMonitor binaries and notices from the official project:

- https://github.com/LibreHardwareMonitor/LibreHardwareMonitor

This repository's source code is MIT licensed. LibreHardwareMonitor and its bundled dependencies retain their upstream licenses and notices in the release ZIP.
