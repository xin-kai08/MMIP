$ErrorActionPreference = 'Stop'
$toolRoot = Join-Path $PSScriptRoot '.tools'
$version = 'v22.14.0'
$name = "node-$version-win-x64.zip"
$target = Join-Path $toolRoot "node-$version-win-x64"
if (Test-Path -LiteralPath (Join-Path $target 'node.exe')) { Write-Output $target; exit 0 }
New-Item -ItemType Directory -Force -Path $toolRoot | Out-Null
$archive = Join-Path $toolRoot $name
Invoke-WebRequest -Uri "https://nodejs.org/dist/$version/$name" -OutFile $archive
$checks = (Invoke-WebRequest -Uri "https://nodejs.org/dist/$version/SHASUMS256.txt" -UseBasicParsing).Content
$expected = (($checks -split "`n" | Where-Object { $_.Trim().EndsWith("  $name") }) -split '\s+')[0]
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $expected -or $actual -ne $expected) { throw 'Node archive SHA-256 mismatch' }
Expand-Archive -LiteralPath $archive -DestinationPath $toolRoot
Write-Output $target
