<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="HardwareMonitor: always-on-top Windows micro-bar for CPU, memory, disk, I/O, and temperature without covering your work.">
</p>

# HardwareMonitor

**Live system telemetry in a thin Windows bar — not a dashboard that eats your screen.**

HardwareMonitor is a low-obstruction, always-on-top micro-bar for watching CPU, memory, disk usage, disk I/O, and hardware temperature status while you work. It is built for people who need live numbers next to documents, terminals, plots, or lab software — without a large floating panel.

## Proof

<p align="center">
  <img src="docs/preview.svg" width="100%" alt="HardwareMonitor micro-bar over sample desktop documents, with expanded trend panel.">
</p>

## Why this shape

| Problem | What HardwareMonitor does |
| --- | --- |
| Full dashboards cover the work | Default bar height about **38 px**, always on top |
| One-line glance is enough | CPU · MEM · DSK · IO · temperature status on one strip |
| Trends only when needed | Click to expand a compact **10-minute** in-memory history |
| Missing sensors lie | Shows **`N/A` / invalid** instead of inventing temperatures |

## How it works

1. Collects CPU, memory, and disk metrics with **psutil**.
2. Reads CPU / disk temperature sensors via **LibreHardwareMonitor** through **pythonnet** when available.
3. Draws a draggable micro-bar; click expands details, move the cursor away to fold.
4. Rejects unavailable or invalid sensor values (including bare `0.0 °C` on some systems).

## Download

**[Latest Release](https://github.com/D-sudoasd/HardwareMonitor/releases/latest)**

Portable ZIP — no Python install required for release users:

1. Download `HardwareMonitor.zip`.
2. Extract it anywhere.
3. Run `HardwareMonitor.exe`.
4. Allow the Windows administrator prompt if you want the best chance of reading hardware temperature sensors.

CPU, memory, disk usage, and disk I/O still work if temperature sensors are unavailable.

## Usage

- **Drag** the micro-bar to reposition it.
- **Left-click** the bar to expand or collapse details.
- **Move the cursor away** from the expanded panel to fold it back.
- **Right-click** for expand/collapse and close.

## Temperature notes

Temperature readings depend on motherboard firmware, CPU/SSD controller support, Windows permissions, and LibreHardwareMonitor support.

If you see `TEMP N/A` or `Temp sensor invalid`:

- Run the app as Administrator.
- Compare with the LibreHardwareMonitor GUI or HWiNFO.
- Treat unavailable sensors as an environment limitation, not as a normal temperature.

## Build from source

Requirements: **Windows**, **Python 3.11+**, **PowerShell**.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python main.py
```

Portable EXE + ZIP:

```powershell
.\scripts\build_exe.ps1
```

Output:

```text
dist\HardwareMonitor\HardwareMonitor.exe
dist\HardwareMonitor.zip
dist\HardwareMonitor.zip.sha256
```

The build script downloads LibreHardwareMonitor from the official GitHub release, vendors required DLLs and license files, runs tests, and packages the app.

## Verify a release ZIP

```powershell
Get-FileHash -Algorithm SHA256 .\HardwareMonitor.zip
Get-Content .\HardwareMonitor.zip.sha256
```

The two hashes should match.

## Development checks

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m py_compile main.py app.py collectors\system_metrics.py collectors\temperature.py models\sample.py ui\floating_monitor.py
```

## License and third-party

- This repository’s source is **MIT**.
- Packaged releases include **LibreHardwareMonitor** binaries and notices from the upstream project: [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor). Those components keep their own licenses inside the release ZIP.
