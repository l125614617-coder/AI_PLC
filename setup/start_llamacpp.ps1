[CmdletBinding()]
param(
    [string]$ModelPath = "",
    [int]$Port = 8082,
    [int]$ContextSize = 8192,
    [ValidateRange(0, 8)]
    [int]$MtpTokens = 2
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$server = Join-Path $projectRoot "tools\llama.cpp\llama-server.exe"
if (-not $ModelPath) {
    $ModelPath = Join-Path $projectRoot "models\Qwen3.6-27B-Q3_K_M.gguf"
}

if (-not (Test-Path -LiteralPath $server)) {
    throw "llama-server.exe not found: $server"
}
if (-not (Test-Path -LiteralPath $ModelPath)) {
    throw "Model not found: $ModelPath"
}

$arguments = @(
    "-m", $ModelPath,
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--ctx-size", "$ContextSize",
    "--gpu-layers", "all",
    "--flash-attn", "on",
    "--jinja",
    "--no-mmproj",
    "--parallel", "1",
    "--metrics"
)
if ($MtpTokens -gt 0) {
    $arguments += @(
        "--spec-type", "draft-mtp",
        "--spec-draft-n-max", "$MtpTokens"
    )
}

Write-Host "Starting llama.cpp on http://127.0.0.1:$Port"
Write-Host "Model: $ModelPath"
Write-Host "Context: $ContextSize | MTP tokens: $MtpTokens"
& $server @arguments
