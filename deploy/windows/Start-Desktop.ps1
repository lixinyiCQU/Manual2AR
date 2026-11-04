# Keep Windows camera capture on a local filesystem. Backend and data remain in WSL.
param([switch]$SpatialDemo, [switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$stateRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Manual2AR'
$channel = 'Desktop'
$manifestPath = Join-Path $source 'delivery.json'
if (Test-Path -LiteralPath $manifestPath) {
    $delivery = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -ne $delivery.visual_asset_library) { $channel = 'Desktop-AssetLibrary' }
}
$destination = Join-Path $stateRoot $channel
$executable = Join-Path $destination 'Manual2AR.exe'
$lock = $null
try {
    if (-not (Test-Path -LiteralPath (Join-Path $source 'Manual2AR.exe'))) {
        throw 'The frontend files are incomplete. Extract the entire delivery folder first.'
    }
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $lock = [IO.File]::Open((Join-Path $stateRoot 'desktop-launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    if ($source -ine $destination) {
        $running = Get-Process Manual2AR -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq $executable }
        if ($running) { throw 'Manual2AR is already running. Close its window before launching the updated demo.' }
        # Robocopy copies only changed files; /MIR also removes obsolete frontend files.
        # This directory contains only disposable frontend binaries, never operator data.
        & robocopy.exe $source $destination /MIR /R:2 /W:1 /NP /NFL /NDL /NJH /NJS | Out-Null
        if ($LASTEXITCODE -ge 8) { throw 'Could not synchronize the frontend to the local Windows disk.' }
    }
    if ($null -ne $delivery -and $delivery.frontend_assembly_sha256) {
        $assembly = Join-Path $destination 'Manual2AR_Data/Managed/Assembly-CSharp.dll'
        $actual = (Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $delivery.frontend_assembly_sha256) { throw 'Frontend assembly does not match the delivery. Re-extract the entire new delivery folder.' }
    }
    if ($PrepareOnly) { Write-Output $destination; exit 0 }
    if ($SpatialDemo) {
        Start-Process -FilePath $executable -ArgumentList '--spatial-demo' -WorkingDirectory $destination
    } else {
        Start-Process -FilePath $executable -WorkingDirectory $destination
    }
} catch {
    Write-Host ('Manual2AR could not start: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($null -ne $lock) { $lock.Dispose() }
}
