param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VendorDir = Join-Path $ProjectRoot "vendor"
$DistDir = Join-Path $ProjectRoot "dist"
$BuildDir = Join-Path $ProjectRoot "build"
$AppDistDir = Join-Path $DistDir "HardwareMonitor"
$ZipPath = Join-Path $DistDir "HardwareMonitor.zip"
$HashPath = "$ZipPath.sha256"
$RepoUrl = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor"

function Assert-InProject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $root = [System.IO.Path]::GetFullPath($ProjectRoot)
    $target = [System.IO.Path]::GetFullPath($Path)
    if (-not $target.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside project root: $target"
    }
}

function Get-PythonCommand {
    if (Test-Path $VenvPython) {
        return $VenvPython
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return $py.Source
    }

    throw "Python was not found. Install Python 3.11+ or create .venv first."
}

function Ensure-Venv {
    if (Test-Path $VenvPython) {
        return
    }

    $python = Get-PythonCommand
    Write-Host "Creating .venv..."
    if ((Split-Path -Leaf $python) -ieq "py.exe") {
        & $python -3 -m venv (Join-Path $ProjectRoot ".venv")
    }
    else {
        & $python -m venv (Join-Path $ProjectRoot ".venv")
    }
}

function Get-LibreHardwareMonitorTag {
    $latestUrl = "$RepoUrl/releases/latest"
    $response = Invoke-WebRequest -Uri $latestUrl -UseBasicParsing
    $uri = $response.BaseResponse.ResponseUri.AbsoluteUri
    $tag = Split-Path ([System.Uri]$uri).AbsolutePath -Leaf
    if (-not $tag -or $tag -notmatch "^v\d+\.\d+\.\d+$") {
        throw "Could not determine LibreHardwareMonitor latest release tag from $uri"
    }
    return $tag
}

function Download-File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [Parameter(Mandatory = $true)]
        [string]$OutFile
    )

    Write-Host "Downloading $Uri"
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
}

function Update-LibreHardwareMonitorVendor {
    New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null

    $tag = Get-LibreHardwareMonitorTag
    $zip = Join-Path ([System.IO.Path]::GetTempPath()) "LibreHardwareMonitor-$tag.zip"
    $extractDir = Join-Path ([System.IO.Path]::GetTempPath()) "LibreHardwareMonitor-$tag"

    Download-File "$RepoUrl/releases/download/$tag/LibreHardwareMonitor.zip" $zip

    if (Test-Path $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }
    Expand-Archive -LiteralPath $zip -DestinationPath $extractDir -Force

    Get-ChildItem -LiteralPath $VendorDir -Force |
        Where-Object { $_.Name -ne "README.md" } |
        Remove-Item -Recurse -Force

    Copy-Item -Path (Join-Path $extractDir "*") -Destination $VendorDir -Recurse -Force

    Download-File "$RepoUrl/raw/$tag/LICENSE" (Join-Path $VendorDir "LICENSE")
    Download-File "$RepoUrl/raw/$tag/THIRD-PARTY-NOTICES.txt" (Join-Path $VendorDir "THIRD-PARTY-NOTICES.txt")

    $dll = Join-Path $VendorDir "LibreHardwareMonitorLib.dll"
    if (-not (Test-Path $dll)) {
        throw "LibreHardwareMonitorLib.dll was not found after extracting $zip"
    }

    Write-Host "Vendored LibreHardwareMonitor $tag"
}

Push-Location $ProjectRoot
try {
    Assert-InProject $VendorDir
    Assert-InProject $DistDir
    Assert-InProject $BuildDir

    Ensure-Venv
    & $VenvPython -m pip install -r requirements-dev.txt

    Update-LibreHardwareMonitorVendor

    if (-not $SkipTests) {
        & $VenvPython -m pytest
        & $VenvPython -m py_compile main.py app.py collectors\system_metrics.py collectors\temperature.py models\sample.py ui\floating_monitor.py
    }

    if (Test-Path $BuildDir) {
        Remove-Item -LiteralPath $BuildDir -Recurse -Force
    }
    if (Test-Path $AppDistDir) {
        Remove-Item -LiteralPath $AppDistDir -Recurse -Force
    }
    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    if (Test-Path $HashPath) {
        Remove-Item -LiteralPath $HashPath -Force
    }

    & $VenvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --contents-directory "." `
        --name "HardwareMonitor" `
        --manifest "packaging\windows-admin.manifest" `
        --add-data "vendor;vendor" `
        --hidden-import "clr" `
        --hidden-import "pythonnet" `
        --collect-submodules "clr_loader" `
        main.py

    $exe = Join-Path $AppDistDir "HardwareMonitor.exe"
    $packedDll = Join-Path $AppDistDir "vendor\LibreHardwareMonitorLib.dll"
    $packedLicense = Join-Path $AppDistDir "vendor\LICENSE"
    $packedThirdParty = Join-Path $AppDistDir "vendor\THIRD-PARTY-NOTICES.txt"
    foreach ($required in @($exe, $packedDll, $packedLicense, $packedThirdParty)) {
        if (-not (Test-Path $required)) {
            throw "Expected build output missing: $required"
        }
    }

    Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination (Join-Path $AppDistDir "README.md") -Force
    Compress-Archive -Path (Join-Path $AppDistDir "*") -DestinationPath $ZipPath -Force

    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath
    "$($hash.Hash)  HardwareMonitor.zip" | Set-Content -LiteralPath $HashPath -Encoding ASCII

    Write-Host "Built $exe"
    Write-Host "Packed $ZipPath"
    Write-Host "SHA256 $($hash.Hash)"
}
finally {
    Pop-Location
}
