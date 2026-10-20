param(
  [Parameter(Mandatory=$true)][string]$SourceRoot,
  [string]$OutputDirectory,
  [string]$WasmBindgen
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
if (!$OutputDirectory) { $OutputDirectory = Join-Path $projectRoot '.next/abstreet-candidate' }
if (!$WasmBindgen) { $WasmBindgen = Join-Path $projectRoot '.next/wasm-tools/bin/wasm-bindgen.exe' }
$sourcePath = (Resolve-Path -LiteralPath $SourceRoot).Path
$revision = & git -C $sourcePath rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or !$revision.StartsWith('c0d3b73')) { throw 'Source must be A/B Street v0.3.49 (c0d3b73).' }
$patchPath = Join-Path $PSScriptRoot 'v0.3.49-traffic-pi.patch'
& git -C $sourcePath apply --reverse --check $patchPath 2>$null
if ($LASTEXITCODE -ne 0) {
  & git -C $sourcePath apply --check $patchPath
  if ($LASTEXITCODE -ne 0) { throw 'Patch does not apply. Use a clean v0.3.49 checkout.' }
  & git -C $sourcePath apply $patchPath
  if ($LASTEXITCODE -ne 0) { throw 'Patch failed.' }
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'zh_cn.rs') -Destination (Join-Path $sourcePath 'widgetry/src/zh_cn.rs')
& cargo +1.75.0 build --manifest-path (Join-Path $sourcePath 'Cargo.toml') -p game --lib --target wasm32-unknown-unknown --no-default-features --features wasm --release --locked
if ($LASTEXITCODE -ne 0) { throw 'Rust build failed; existing deployment was not changed.' }
& $WasmBindgen (Join-Path $sourcePath 'target/wasm32-unknown-unknown/release/game.wasm') --out-dir $OutputDirectory --target web --out-name game
if ($LASTEXITCODE -ne 0) { throw 'WASM generation failed; existing deployment was not changed.' }
Write-Output "Candidate generated in $OutputDirectory. Validate JS/WASM together before replacing the deployed pair."
