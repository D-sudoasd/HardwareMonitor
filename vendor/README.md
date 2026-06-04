# Vendor Files

This directory is intentionally kept almost empty in source control.

The build script downloads the official LibreHardwareMonitor release and places the required DLLs, notices, and supporting files here before packaging:

```powershell
.\scripts\build_exe.ps1
```

Do not commit downloaded LibreHardwareMonitor binaries to the source repository. They are distributed only inside the GitHub Release ZIP together with upstream license and third-party notices.
