# Keep Windows camera capture on a local filesystem. Backend and data remain in WSL.
param([switch]$SpatialDemo, [switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$stateRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Manual2AR'
$destination = Join-Path $stateRoot 'Desktop'
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
