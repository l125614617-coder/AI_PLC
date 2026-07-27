[CmdletBinding()]
param(
    [string]$Version = "0.2.1"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
$releaseRoot = Join-Path $projectRoot "release"
$packageDir = Join-Path $releaseRoot "PLC-Assist-$Version"
$workDir = Join-Path $projectRoot ".tmp\pyinstaller-$Version"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python"
}
& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Run: .\venv\Scripts\python.exe -m pip install -r requirements-dev.txt"
}

$resolvedRelease = [IO.Path]::GetFullPath($releaseRoot)
$resolvedPackage = [IO.Path]::GetFullPath($packageDir)
if (-not $resolvedPackage.StartsWith($resolvedRelease + [IO.Path]::DirectorySeparatorChar)) {
    throw "Unsafe package path: $resolvedPackage"
}
if (Test-Path -LiteralPath $resolvedPackage) {
    Remove-Item -LiteralPath $resolvedPackage -Recurse -Force
}
New-Item -ItemType Directory -Path $resolvedPackage -Force | Out-Null
New-Item -ItemType Directory -Path $workDir -Force | Out-Null

$files = @(
    "app.py", "app_codex.py", "app_llamacpp.py", "benchmark_local_models.py",
    "codex_provider.py", "compiler.py", "local_provider.py", "plc_config.py",
    "scenarios.py", "simulator.py", "st_common.py", "validator.py",
    "README.md", "DEPLOYMENT.md", "RELEASE_NOTES.md",
    "requirements.txt", "requirements-dev.txt",
    "hardware_config.example.env"
)
foreach ($relative in $files) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $relative) -Destination $packageDir -Force
}
Copy-Item -LiteralPath (Join-Path $projectRoot "motion_stubs") -Destination $packageDir -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $packageDir "setup") -Force | Out-Null
foreach ($relative in @(
    "build_release.ps1", "run_openplc.py", "setup_windows_toolchain.ps1",
    "start_llamacpp.ps1", "start_openplc.sh"
)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $relative) -Destination (Join-Path $packageDir "setup") -Force
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "PLC-Assist-Service-Manager" `
    --distpath $packageDir `
    --workpath $workDir `
    --specpath $workDir `
    (Join-Path $projectRoot "service_manager.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "PLC-Assist-Service-CLI" `
    --distpath $packageDir `
    --workpath (Join-Path $workDir "cli") `
    --specpath $workDir `
    (Join-Path $projectRoot "service_manager.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller CLI build failed with exit code $LASTEXITCODE"
}

$archive = Join-Path $projectRoot "release\PLC-Assist-$Version-win64.zip"
Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $archive -Force
Write-Output "PACKAGE=$packageDir"
Write-Output "ARCHIVE=$archive"
