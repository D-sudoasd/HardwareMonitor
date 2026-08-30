# Changelog

## Unreleased — vNext

- Moved native telemetry collection to a recoverable background worker with
  explicit freshness/error state and deterministic shutdown.
- Added finite temperature validation, retained DLL search-path handles, and
  idempotent LibreHardwareMonitor close handling.
- Normal packaged launch now uses `asInvoker`; administrator restart is an
  explicit user action. Added persisted position/opacity/pin/auto-collapse settings
  and a Show/Hide/Quit tray path with a no-tray fallback.
- Clarified `SYS C:` capacity versus `IO ALL` aggregate I/O, and improved trend
  legend, scale, time labels, keyboard access, and compact-bar readability.
- Hardened timeout shutdown: a blocked native collector keeps ownership and a
  visible `WAIT` state until it returns, then closes exactly once.
- Added an offline `-ProbeOnly` build check for executable Python 3.11+
  selection, non-finite system-rate guards, safe malformed-position fallback,
  wall-clock-ordered history, and valid temperature descendants after a parent
  update failure.
- Hardened immediate startup/quit handoff with a queued, lifecycle-safe worker
  stop request, a stop-intent cycle guard, and a no-tray quit accessible name.

## v1.0.0 - 2026-06-04

- First public release.
- Added a low-obstruction Windows micro-bar for CPU, memory, disk usage, disk I/O, and temperature status.
- Added click-to-expand trend details with a 10-minute in-memory history.
- Added LibreHardwareMonitor-based temperature support with explicit invalid-sensor handling.
- Added PyInstaller packaging script and portable ZIP release workflow.
