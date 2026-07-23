<#
.SYNOPSIS
  Bootstraps the Windows-native toolchain the PLC-Assist compile/simulate
  pipeline needs: MSYS2 (gcc/make/git), OpenPLC_v3 built from source (matiec's
  iec2c.exe + the openplc runtime), and the pymodbus/requests Python packages
  in this project's own venv.

.DESCRIPTION
  Captures the manual steps performed while first standing up this pipeline,
  including two real environment bugs found and fixed along the way:
    1. MSYS2's first-run core update needs two `pacman -Syu` passes (the
       first replaces msys2-runtime itself and self-terminates the shell --
       that's expected, not a failure).
    2. OpenPLC_v3's win_msys2 install path hardcodes a Cygwin-era
       /usr/local/include/modbus, /usr/local/lib path convention that does
       not match where pacman actually installs libmodbus under MSYS2's
       MINGW64 prefix (/mingw64/include, /mingw64/lib) -- this script mirrors
       the files to the expected location before compiling.

  Safe to re-run: each step checks whether its result already exists and
  skips accordingly, except the OpenPLC_v3 clone + install.sh invocation,
  which assumes a fresh machine (delete the OpenPLC_v3 folder under the MSYS2
  home directory to force a clean reinstall).

.NOTES
  Run from an ordinary PowerShell prompt (elevation is only requested by the
  winget/MSYS2 installer itself, not by this script). Takes 5-15 minutes
  depending on network speed; most of that is package downloads and the
  OpenDNP3/glue_generator/matiec builds.
#>

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Invoke-Msys2Bash([string]$Command) {
    & "C:\msys64\usr\bin\bash.exe" -lc $Command
    if ($LASTEXITCODE -ne 0) {
        throw "MSYS2 bash command failed (exit $LASTEXITCODE): $Command"
    }
}

# ---------------------------------------------------------------------------
Write-Step "Checking for MSYS2"
if (-not (Test-Path "C:\msys64\usr\bin\bash.exe")) {
    Write-Step "Installing MSYS2 via winget"
    winget install --id MSYS2.MSYS2 -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget install of MSYS2 failed" }
} else {
    Write-Host "MSYS2 already installed at C:\msys64"
}

# ---------------------------------------------------------------------------
Write-Step "Running MSYS2 first-time core update (pass 1 of 2 -- this pass self-terminates the shell, that's expected)"
& "C:\msys64\usr\bin\bash.exe" -lc "pacman -Syu --noconfirm" | Out-Null

Write-Step "Running MSYS2 core update (pass 2 of 2)"
Invoke-Msys2Bash "pacman -Syu --noconfirm"

# ---------------------------------------------------------------------------
Write-Step "Installing build toolchain packages (gcc, git, make, autoconf, etc.)"
Invoke-Msys2Bash "pacman -S --noconfirm gcc git pkg-config automake autoconf libtool make sqlite3 python3"

# ---------------------------------------------------------------------------
Write-Step "Cloning OpenPLC_v3 into the MSYS2 home directory"
Invoke-Msys2Bash "test -d ~/OpenPLC_v3 || git clone --depth 1 https://github.com/thiagoralves/OpenPLC_v3.git ~/OpenPLC_v3"

# ---------------------------------------------------------------------------
Write-Step "Running OpenPLC_v3's win_msys2 install (builds matiec/glue_generator/st_optimizer, installs libmodbus)"
Invoke-Msys2Bash "cd ~/OpenPLC_v3 && ./install.sh win_msys2"

# ---------------------------------------------------------------------------
Write-Step "Fixing libmodbus header/lib path mismatch (pacman installs under /mingw64, OpenPLC's Windows build script expects /usr/local)"
Invoke-Msys2Bash @"
mkdir -p /usr/local/include/modbus /usr/local/lib
cp -n /mingw64/include/modbus/*.h /usr/local/include/modbus/
cp -n /mingw64/lib/libmodbus.a /mingw64/lib/libmodbus.la /usr/local/lib/
"@

# ---------------------------------------------------------------------------
Write-Step "Retrying the blank-program compile (this is the step the path mismatch above breaks on first install)"
Invoke-Msys2Bash "cd ~/OpenPLC_v3/webserver/scripts && ./change_hardware_layer.sh blank && ./compile_program.sh blank_program.st"

# ---------------------------------------------------------------------------
Write-Step "Verifying the build artifacts"
$openplcDir = "C:\msys64\home\$env:USERNAME\OpenPLC_v3"
$requiredFiles = @(
    "$openplcDir\webserver\iec2c.exe",
    "$openplcDir\webserver\core\openplc.exe",
    "$openplcDir\.venv\bin\python3"
)
foreach ($f in $requiredFiles) {
    if (-not (Test-Path $f)) { throw "Expected build artifact missing: $f" }
    Write-Host "  OK: $f"
}

# ---------------------------------------------------------------------------
Write-Step "Installing pymodbus/requests into this project's own venv"
$projectDir = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectDir "venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m pip install --quiet "pymodbus==2.5.3" requests
} else {
    Write-Host "  (no venv found at $venvPython -- skipping; install pymodbus==2.5.3 and requests into whatever Python app.py runs under)"
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "OpenPLC_v3 is installed at: $openplcDir"
Write-Host "Start its webserver with:"
Write-Host "  C:\msys64\usr\bin\bash.exe -lc `"cd ~/OpenPLC_v3/webserver && ~/OpenPLC_v3/.venv/bin/python3 webserver.py`""
Write-Host "compiler.py and simulator.py resolve OpenPLC_v3's location from `$env:USERNAME automatically -- no further configuration needed."
