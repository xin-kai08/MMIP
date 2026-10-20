param([ValidateSet('install','dev','build')][string]$Action='build')
$ErrorActionPreference='Stop'
$nodeDir=Join-Path $PSScriptRoot '.tools\node-v22.14.0-win-x64'
if (-not (Test-Path -LiteralPath (Join-Path $nodeDir 'node.exe'))) { throw 'Run website\bootstrap_node.ps1 first.' }
$env:PATH=$nodeDir+';'+$env:PATH
$env:npm_config_cache=Join-Path $PSScriptRoot '.cache\npm'
Push-Location (Join-Path $PSScriptRoot 'frontend')
try {
    if ($Action -eq 'install') { & (Join-Path $nodeDir 'node.exe') (Join-Path $nodeDir 'node_modules\npm\bin\npm-cli.js') ci --no-audit --no-fund }
    else { & (Join-Path $nodeDir 'node.exe') (Join-Path $nodeDir 'node_modules\npm\bin\npm-cli.js') run $Action }
    if ($LASTEXITCODE -ne 0) { throw "Frontend command failed: $LASTEXITCODE" }
} finally { Pop-Location }
