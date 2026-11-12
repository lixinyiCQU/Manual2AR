# Resolve WSL at launch time; never assume the build machine's distribution name.
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
try {
    $config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'backend.launch.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $wsl = Join-Path $env:WINDIR 'System32\wsl.exe'
    $installed = @(& $wsl --list --quiet | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
    if ($LASTEXITCODE -ne 0 -or $installed.Count -eq 0) { throw 'No available WSL distribution was found.' }
    $uncDistribution = ''
    if ($PSScriptRoot -match '^\\\\(?:wsl\$|wsl\.localhost)\\([^\\]+)\\') { $uncDistribution = $Matches[1] }
    $candidates = @(@($uncDistribution, $config.distribution_hint) + $installed | Where-Object { $_ } | Select-Object -Unique)
    $selected = $null
    foreach ($candidate in $candidates) {
        if ($installed -notcontains $candidate) { continue }
        & $wsl --distribution $candidate --exec /usr/bin/test -f ($config.worktree.TrimEnd('/') + '/run.sh') 2>$null
        if ($LASTEXITCODE -eq 0) { $selected = $candidate; break }
    }
    if (-not $selected) { throw 'The source worktree was not found in any installed WSL distribution. Check backend.launch.json.' }
    if ($CheckOnly) {
        @{ distribution = $selected; worktree = $config.worktree } | ConvertTo-Json -Compress
        exit 0
    }
    Write-Host ('Manual2AR backend | WSL: ' + $selected + ' | ' + $config.worktree)
    $health = $null
    try { $health = Invoke-RestMethod -Uri ($config.backend_url.TrimEnd('/') + '/health') -TimeoutSec 3 } catch { }
    if ($null -ne $health) {
        $spatial = $null
        try { $spatial = Invoke-RestMethod -Uri ($config.backend_url.TrimEnd('/') + '/api/guidance/spatial/config') -TimeoutSec 3 } catch { }
        if ($null -ne $spatial -and $spatial.automatic_configuration -eq $true -and $config.backend_revision -and $health.backend_revision -ceq $config.backend_revision -and $health.source_worktree -ceq $config.worktree) {
            Write-Host 'The compatible backend is already running. Return to the tutorial and re-enter AR guidance.'
            exit 0
        }
        throw 'An older or incompatible backend is already using this address. Close its backend terminal, then run this launcher again.'
    }
    & $wsl --distribution $selected --cd $config.worktree --exec bash run.sh start
    if ($LASTEXITCODE -ne 0) { throw ('Backend exited with code ' + $LASTEXITCODE + '. See the messages above.') }
} catch {
    Write-Host ('Manual2AR backend could not start: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
