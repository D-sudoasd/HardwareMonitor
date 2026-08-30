param(
    [switch]$SkipTests,
    [switch]$ProbeOnly
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
        if (Test-PythonExecutable -Executable $VenvPython) {
            return $VenvPython
        }
        Write-Warning "Configured .venv interpreter is not executable: $VenvPython"
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-PythonExecutable -Executable $python.Source)) {
        return $python.Source
    }
    if ($python) {
        Write-Warning "Skipping non-working python candidate: $($python.Source)"
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-PythonExecutable -Executable $py.Source -PrefixArguments @('-3'))) {
        return $py.Source
    }

    throw "No executable Python 3.11+ interpreter was found. Install Python 3.11+ or create .venv first."
}

function Test-PythonExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    $version = Get-PythonVersion -Executable $Executable -PrefixArguments $PrefixArguments
    if (-not $version) {
        return $false
    }
    try {
        return [version]$version -ge [version]'3.11'
    }
    catch {
        return $false
    }
}

function Get-PythonVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    try {
        $output = @(& $Executable @PrefixArguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null)
        if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) {
            return $null
        }
        $version = ([string]$output[0]).Trim()
        if ($version -notmatch '^\d+\.\d+(\.\d+)?$') {
            return $null
        }
        return $version
    }
    catch {
        return $null
    }
}

function Get-PythonPrefixArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable
    )

    if ((Split-Path -Leaf $Executable) -ieq "py.exe") {
        return @("-3")
    }
    return @()
}

function Ensure-Venv {
    if ((Test-Path $VenvPython) -and (Test-PythonExecutable -Executable $VenvPython)) {
        return
    }

    $python = Get-PythonCommand
    $pythonArguments = Get-PythonPrefixArguments -Executable $python
    Write-Host "Creating .venv..."
    & $python @pythonArguments -m venv (Join-Path $ProjectRoot ".venv")
    if (-not (Test-PythonExecutable -Executable $VenvPython)) {
        throw "The newly created .venv interpreter is not executable: $VenvPython"
    }
}

function Get-OptionalPropertyValue {
    param(
        [AllowNull()]
        [object]$InputObject,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($null -eq $InputObject) {
        return $null
    }
    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Get-LibreHardwareMonitorTag {
    $latestUrl = "$RepoUrl/releases/latest"
    $response = Invoke-WebRequest -Uri $latestUrl -UseBasicParsing
    # Windows PowerShell exposes BaseResponse.ResponseUri, while recent
    # PowerShell 7 builds can expose only the final request URI or a Location
    # header.  Resolve all supported shapes before parsing the tag.
    $uri = $null
    $baseResponse = Get-OptionalPropertyValue -InputObject $response -Name "BaseResponse"
    $responseUri = Get-OptionalPropertyValue -InputObject $baseResponse -Name "ResponseUri"
    if ($responseUri) {
        $uri = [System.Uri]$responseUri
    }
    if (-not $uri) {
        $requestMessage = Get-OptionalPropertyValue -InputObject $baseResponse -Name "RequestMessage"
        $requestUri = Get-OptionalPropertyValue -InputObject $requestMessage -Name "RequestUri"
        if ($requestUri) {
            $uri = [System.Uri]$requestUri
        }
    }
    $headers = Get-OptionalPropertyValue -InputObject $response -Name "Headers"
    $location = Get-OptionalPropertyValue -InputObject $headers -Name "Location"
    if (-not $uri -and $location) {
        $uri = [System.Uri]::new([System.Uri]$latestUrl, [string]$location)
    }
    if (-not $uri) {
        throw "Could not determine LibreHardwareMonitor release URL from $latestUrl"
    }
    $tag = Split-Path $uri.AbsolutePath -Leaf
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

    if ($ProbeOnly) {
        $selectedPython = Get-PythonCommand
        $selectedPrefix = Get-PythonPrefixArguments -Executable $selectedPython
        $selectedVersion = Get-PythonVersion -Executable $selectedPython -PrefixArguments $selectedPrefix
        Write-Output "selected_python=$selectedPython"
        Write-Output "selected_python_version=$selectedVersion"
        return
    }

    Ensure-Venv
    & $VenvPython -m pip install -r requirements-dev.txt

    Update-LibreHardwareMonitorVendor

    if (-not $SkipTests) {
        & $VenvPython -m pytest
        & $VenvPython -m py_compile main.py app.py settings.py windows_integration.py collectors\system_metrics.py collectors\temperature.py models\sample.py ui\floating_monitor.py
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
