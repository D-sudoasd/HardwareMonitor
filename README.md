<p align="center">
  <img src="assets/readme/hero.png" width="100%" alt="HardwareMonitor — Keep desktop hardware activity visible without a large dashboard / 以紧凑桌面状态栏查看硬件活动. Conceptual illustration / 概念插图。">
</p>

# HardwareMonitor

**CPU、内存、磁盘与温度状态，放在一个可拖动的 Windows 桌面状态栏中。**

A compact Windows telemetry bar for keeping live system activity beside your documents, terminals, and analysis software. Expand the recent history only when you need to inspect a trend.

[Windows 下载](https://github.com/D-sudoasd/HardwareMonitor/releases/latest) · [当前源码用法](#usage-current-source) · [温度读数说明](#temperature-notes) · [更新记录](CHANGELOG.md)

[![MIT](https://img.shields.io/badge/License-MIT-455A64)](LICENSE)

![界面布局示意：紧凑状态栏及展开的历史面板，图中数值为演示值](docs/preview.svg)

*上图是仓库已有的界面布局示意，不是当前机器的测量截图。*

| 日常查看 | 需要进一步检查时 |
| --- | --- |
| CPU、内存、系统盘容量与全部磁盘 I/O | 点击状态栏，展开最近 10 分钟的变化 |
| 温度传感器状态 | 缺失或无效读数显示 `N/A`；查看温度说明 |
| 后台采集状态 | 采集失败时标明使用上次读数，恢复后更新 |

**选择下载版还是源码版。** 已发布的 `v1.0.0` 会在启动时请求管理员权限；当前源码另有普通启动、手动管理员重启、托盘和设置保存等更新。下方分别说明下载和源码使用方法。

## How it works

1. Collects CPU, memory, and disk metrics with **psutil**.
2. Reads temperature via **LibreHardwareMonitor** through **pythonnet** when available.
3. Collects in a background worker so a slow native sensor cannot freeze the bar.
4. Draws a draggable micro-bar; click (or Enter/Space) expands details; move away to fold when auto-collapse is enabled.
5. Rejects unavailable or invalid sensors (including `NaN`, infinity, and bare `0.0 °C` on some systems).

<p align="center">
  <img src="assets/readme/section-02-use.svg" width="100%" alt="02 Use: portable ZIP extract and run.">
</p>

## Download

**[Latest Release](https://github.com/D-sudoasd/HardwareMonitor/releases/latest)**

1. Download `HardwareMonitor.zip`.
2. Extract it anywhere.
3. Run `HardwareMonitor.exe`.

The published **v1.0.0** executable requests administrator privileges at startup. The current source includes unreleased improvements: normal launch without UAC, explicit **Restart as administrator**, a tray menu, persisted settings, and background sensor collection. Build or run the current source to use these improvements; see [CHANGELOG.md](CHANGELOG.md).

已发布的 **v1.0.0** 启动时会请求管理员权限。普通启动无需 UAC、手动管理员重启、托盘菜单、设置保存和后台采集属于当前源码中的未发布更新；使用这些功能请从源码运行或构建。

CPU, memory, disk, and I/O still work when temperature is unavailable.

## Usage (current source)

- **Drag** to reposition · **Left-click** expand/collapse · **Enter/Space** expand/collapse · **Escape** collapse · **Move away** to fold · **Right-click/Menu** for actions
- The tray menu provides **Show**, **Hide**, and **Quit**. If Windows reports no tray, closing the bar exits normally instead of leaving a headless process.
- Position, opacity, auto-collapse, and pin preferences are restored across launches. **Reset position** returns the bar to the current screen's top-right corner.

The expanded view distinguishes the capacity scope (`SYS C:` by default) from aggregate I/O (`IO ALL`, all disks). `Starting…` is shown before the first sample; after a recoverable cycle failure the last good values remain visible with `Update failed — showing last sample` and the diagnostic provider message in the tooltip. Successful recovery replaces that stale tooltip. Very large rates use compact binary units in the bar while the tooltip keeps the complete MB/s values. If a native collector is still blocked during Quit, the bar remains visible as `WAIT` until it returns and can be closed safely.

## Temperature notes

Readings depend on firmware, controller support, Windows permissions, and LibreHardwareMonitor. If you see `TEMP N/A` or invalid, use the explicit **Restart as administrator** action, compare with LibreHardwareMonitor/HWiNFO, and treat missing sensors as environment limits.

## Build from source

Windows · Python 3.11+ · PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python main.py
.\scripts\build_exe.ps1
```

Output: `dist\HardwareMonitor\HardwareMonitor.exe`, `dist\HardwareMonitor.zip`, and `dist\HardwareMonitor.zip.sha256`.

To verify the release interpreter choice without installing dependencies or downloading LibreHardwareMonitor, run:

```powershell
.\scripts\build_exe.ps1 -ProbeOnly
```

The probe checks that the interpreter executes and is Python 3.11 or newer, skips a non-working WindowsApps alias, and reports the selected executable/version. In a no-tray environment the visible action is labelled **Quit (no tray available)** because hiding would otherwise leave no recovery path.

## Verify a release ZIP

```powershell
Get-FileHash -Algorithm SHA256 .\dist\HardwareMonitor.zip
Get-Content .\dist\HardwareMonitor.zip.sha256
```

## Development checks

```powershell
.\.venv\Scripts\python -m pytest
```

## License

MIT. Packaged releases include [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) binaries under their upstream licenses.
