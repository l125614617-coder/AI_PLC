<#
.SYNOPSIS
  Installs the Windows-native OpenPLC toolchain used by PLC-Assist.

.DESCRIPTION
  Installs/updates MSYS2, installs the build dependencies, clones and builds
  OpenPLC_v3, applies a libmodbus compatibility fix for current MSYS2 package
  layouts, and verifies the files used by compiler.py and simulator.py.

  The script is safe to run again after a partial installation.
#>

[CmdletBinding()]
param(
    [switch]$SkipMsys2Update
)

$ErrorActionPreference = "Stop"
$Msys2Root = "C:\msys64"
$Msys2Bash = Join-Path $Msys2Root "usr\bin\bash.exe"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Msys2Bash([string]$Command, [switch]$AllowFailure) {
    & $script:Msys2Bash -lc $Command
    $exitCode = $LASTEXITCODE
    if (($exitCode -ne 0) -and (-not $AllowFailure)) {
        throw "MSYS2 bash command failed (exit $exitCode)."
    }
    return $exitCode
}

Write-Step "Checking for MSYS2"
if (-not (Test-Path $Msys2Bash)) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "MSYS2 is not installed and winget was not found. Install MSYS2 from https://www.msys2.org and run this script again."
    }

    winget install --id MSYS2.MSYS2 -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install MSYS2 (exit $LASTEXITCODE)."
    }
}
Write-Host "  OK: $Msys2Bash"

if (-not $SkipMsys2Update) {
    Write-Step "Updating MSYS2 core packages (first pass may terminate its own shell)"
    Invoke-Msys2Bash "pacman -Syu --noconfirm" -AllowFailure | Out-Null

    Write-Step "Finishing the MSYS2 package update"
    Invoke-Msys2Bash "pacman -Syu --noconfirm" | Out-Null
}

Write-Step "Installing OpenPLC build dependencies"
Invoke-Msys2Bash "pacman -S --needed --noconfirm gcc git pkg-config automake autoconf libtool make sqlite3 python3 mingw-w64-x86_64-libmodbus" | Out-Null

Write-Step "Cloning OpenPLC_v3 (skipped when already present)"
Invoke-Msys2Bash "test -d ~/OpenPLC_v3/.git || git clone --depth 1 https://github.com/thiagoralves/OpenPLC_v3.git ~/OpenPLC_v3" | Out-Null

Write-Step "Building OpenPLC_v3"
Invoke-Msys2Bash "cd ~/OpenPLC_v3 && ./install.sh win_msys2"

Write-Step "Applying OpenPLC libmodbus compatibility paths"
$libmodbusFix = @'
set -e
mkdir -p /usr/local/include/modbus /usr/local/lib

# OpenPLC builds a patched libmodbus with extra RPi functions into /usr.
# Always keep its headers and library together.  The stock mingw64 package
# does not declare those functions and must only be a last-resort fallback.
if [ -d /usr/include/modbus ]; then
    cp -f /usr/include/modbus/*.h /usr/local/include/modbus/
elif [ -d /mingw64/include/modbus ]; then
    cp -f /mingw64/include/modbus/*.h /usr/local/include/modbus/
fi

for library in libmodbus.a libmodbus.la libmodbus.dll.a; do
    if [ -f "/usr/lib/$library" ]; then
        cp -f "/usr/lib/$library" /usr/local/lib/
    elif [ -f "/mingw64/lib/$library" ]; then
        cp -f "/mingw64/lib/$library" /usr/local/lib/
    fi
done

# New MSYS2 packages provide an import library named libmodbus.dll.a while
# older OpenPLC scripts may ask the linker for the legacy libmodbus.a name.
if [ ! -f /usr/local/lib/libmodbus.a ] &&
   [ -f /usr/local/lib/libmodbus.dll.a ]; then
    cp -f /usr/local/lib/libmodbus.dll.a /usr/local/lib/libmodbus.a
fi
'@
Invoke-Msys2Bash $libmodbusFix | Out-Null

Write-Step "Compiling OpenPLC's blank program"
Invoke-Msys2Bash "cd ~/OpenPLC_v3/webserver/scripts && ./change_hardware_layer.sh blank && ./compile_program.sh blank_program.st"

Write-Step "Verifying build artifacts"
$openplcDir = Join-Path $Msys2Root "home\$env:USERNAME\OpenPLC_v3"
$requiredFiles = @(
    (Join-Path $openplcDir "webserver\iec2c.exe"),
    (Join-Path $openplcDir "webserver\core\openplc.exe"),
    (Join-Path $openplcDir ".venv\bin\python3")
)
foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) {
        throw "Expected build artifact is missing: $file"
    }
    Write-Host "  OK: $file"
}

Write-Step "Installing PLC-Assist Python dependencies"
$projectDir = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectDir "venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m pip install --quiet "pymodbus==2.5.3" requests
    if ($LASTEXITCODE -ne 0) {
        throw "pip could not install pymodbus/requests (exit $LASTEXITCODE)."
    }
} else {
    Write-Warning "No project venv was found at $venvPython. Run: python -m venv venv"
}

Write-Host ""
Write-Host "OpenPLC setup complete." -ForegroundColor Green
Write-Host "Installed at: $openplcDir"
Write-Host "Start the webserver with:"
Write-Host '  C:\msys64\usr\bin\bash.exe -lc "cd ~/OpenPLC_v3/webserver && ~/OpenPLC_v3/.venv/bin/python3 webserver.py"'
