param([switch]$NoBrowser, [switch]$SmokeTest, [switch]$RequireScheduler)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$serverProcess = $null
$instance = $null
$startupMutex = $null
$ownsStartupMutex = $false
$exitCode = 0
function Invoke-SetupCommand {
    param([string]$Executable, [string[]]$CommandArguments, [string]$FailureMessage)
    # Windows PowerShell 5.1 wraps redirected native stderr in ErrorRecord.
    # Tools legitimately use stderr for progress and warnings even on success.
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Executable @CommandArguments 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $setupLog -Append
        $nativeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($nativeExitCode -ne 0) { throw "$FailureMessage See $setupLog" }
}
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot 'logs') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot 'data') | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $setupLog = Join-Path $projectRoot "logs\setup-$stamp.log"
    # Parse only KEY=VALUE; never execute .env content or change machine settings.
    $dotenv = Join-Path $projectRoot '.env'
    if (Test-Path -LiteralPath $dotenv) {
        foreach ($line in Get-Content -LiteralPath $dotenv) {
            if ($line -match '^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$') {
                [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim('"').Trim("'"), 'Process')
            }
        }
    }
    # Serialize setup, port selection, and startup for this exact workspace.
    $workspacePath = $projectRoot.ToLowerInvariant()
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $workspaceId = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($workspacePath))).Replace('-', '').ToLowerInvariant()
    $sha.Dispose()
    $startupMutex = New-Object System.Threading.Mutex($false, "Local\DaycraftStartup-$workspaceId")
    try { $ownsStartupMutex = $startupMutex.WaitOne(60000) } catch [System.Threading.AbandonedMutexException] { $ownsStartupMutex = $true }
    if (-not $ownsStartupMutex) { throw 'Another Daycraft launcher is still starting. Try again after setup finishes.' }
    $port = 8765
    if ($env:SCHEDULE_BUILDER_PORT) { $port = [int]$env:SCHEDULE_BUILDER_PORT }
    if ($port -lt 1024 -or $port -gt 65525) { throw 'Port must be between 1024 and 65525.' }
    $databasePath = Join-Path $projectRoot 'data\schedule_builder.db'
    if ($env:SCHEDULE_BUILDER_DB) { $databasePath = [IO.Path]::GetFullPath($env:SCHEDULE_BUILDER_DB) }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $databaseId = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($databasePath.ToLowerInvariant()))).Replace('-', '').ToLowerInvariant()
    $sha.Dispose()
    # Reuse before dependency installation or migration; reject other workspaces/databases.
    for ($candidate = $port; $candidate -lt $port + 10; $candidate++) {
        $existing = $null
        $health = $null
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$candidate/health" -TimeoutSec 1 } catch { }
        if ($health.app -ne 'schedule-builder') { continue }
        try { $existing = Invoke-RestMethod -Uri "http://127.0.0.1:$candidate/_daycraft/runtime" -TimeoutSec 1 } catch { }
        if (-not $existing.workspace) { throw "An older Daycraft instance is running on port $candidate without verified lifecycle identity. Close its original launcher before restarting. No process was stopped." }
        if ($existing.workspace -ne $workspaceId -or $existing.database -ne $databaseId -or $health.status -ne 'ok') { continue }
        $liveSolver = $null
        try {
            $liveSolver = Invoke-RestMethod -Uri "http://127.0.0.1:$candidate/api/solver-health" -TimeoutSec 20
        } catch {
            # Windows PowerShell throws on 503 but keeps the public JSON body.
            try { $liveSolver = $_.ErrorDetails.Message | ConvertFrom-Json } catch { }
        }
        $liveReady = $liveSolver.status -eq 'operational' -and $liveSolver.code -eq 'ready' -and $liveSolver.solver_status -in @('FEASIBLE', 'OPTIMAL')
        if ($liveReady) { Write-Host 'Scheduling ready: running instance passed an actual CP-SAT test solve.' -ForegroundColor Green }
        else {
            Write-Host "Scheduling unavailable: $($liveSolver.message) Review docs\WINDOWS_RUNTIME.md." -ForegroundColor Yellow
            if ($RequireScheduler) { throw 'Required scheduling self-test failed on the existing instance. No process was stopped.' }
        }
        Write-Host "Schedule Builder is already running at http://127.0.0.1:$candidate"
        if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$candidate" }
        exit 0
    }
    Write-Host 'Schedule Builder | Local daily planner' -ForegroundColor Cyan
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $systemPython = Get-Command python -ErrorAction SilentlyContinue
        if (-not $systemPython) { throw 'Python 3.11+ is required. Install Python from python.org, enable PATH, and run this file again.' }
        Invoke-SetupCommand -Executable $systemPython.Source -CommandArguments @('-m', 'venv', (Join-Path $projectRoot '.venv')) -FailureMessage 'Could not create the project Python environment.'
    }
    & $python -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required. Rename the old .venv folder after upgrading Python.' }
    $requirements = Join-Path $projectRoot 'backend\requirements.txt'
    $lock = Join-Path $projectRoot 'backend\requirements.lock.txt'
    if (Test-Path -LiteralPath $lock) { $requirements = $lock }
    $dependencyHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $dependencyStamp = Join-Path $projectRoot '.venv\.requirements-hash'
    $installPython = -not (Test-Path -LiteralPath $dependencyStamp)
    if (-not $installPython) { $installPython = (Get-Content -LiteralPath $dependencyStamp -Raw).Trim() -ne $dependencyHash }
    if ($installPython) {
        Write-Host 'Installing project Python dependencies (first run may take several minutes)...'
        Invoke-SetupCommand -Executable $python -CommandArguments @('-m', 'pip', 'install', '--no-input', '--no-cache-dir', '--disable-pip-version-check', '--retries', '1', '--timeout', '30', '-r', $requirements) -FailureMessage 'Dependency installation failed. Check your network.'
        Set-Content -LiteralPath $dependencyStamp -Value $dependencyHash -Encoding ASCII
    }
    # A bounded same-venv child must actually solve before reporting readiness.
    $solverReport = Join-Path $projectRoot "logs\solver-health-$stamp.json"
    $solverLog = Join-Path $projectRoot "logs\solver-health-$stamp.err.log"
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $python -m backend.app.solver_health 1> $solverReport 2> $solverLog
        $solverExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousErrorAction }
    $solverReady = $false
    $solverMessage = 'The scheduling runtime check did not produce a valid result.'
    try {
        $solverHealth = Get-Content -LiteralPath $solverReport -Raw | ConvertFrom-Json
        $solverReady = $solverExit -eq 0 -and $solverHealth.status -eq 'operational' -and $solverHealth.code -eq 'ready' -and $solverHealth.solver_status -in @('OPTIMAL', 'FEASIBLE')
        $solverMessage = $solverHealth.message
    } catch { }
    if ($solverReady) {
        Write-Host 'Scheduling ready: CP-SAT passed an actual test solve.' -ForegroundColor Green
    } else {
        Write-Host "Scheduling unavailable: $solverMessage" -ForegroundColor Yellow
        Write-Host "Diagnostics: $solverLog"
        Write-Host "Recovery guide: $(Join-Path $projectRoot 'docs\WINDOWS_RUNTIME.md')"
        if ($RequireScheduler) { throw 'Required scheduling self-test failed. No schedule was generated.' }
        Write-Host 'The workspace can still open; schedule generation remains unavailable.' -ForegroundColor Yellow
    }
    $frontend = Join-Path $projectRoot 'frontend'
    $dist = Join-Path $frontend 'dist\index.html'
    $buildRequired = -not (Test-Path -LiteralPath $dist)
    if (-not $buildRequired) {
        $distTime = (Get-Item -LiteralPath $dist).LastWriteTimeUtc
        $sources = @(Get-ChildItem -LiteralPath (Join-Path $frontend 'src') -File -Recurse)
        $sources += @(Get-Item -LiteralPath (Join-Path $frontend 'package-lock.json'), (Join-Path $frontend 'package.json'), (Join-Path $frontend 'tsconfig.json'), (Join-Path $frontend 'index.html'), (Join-Path $frontend 'vite.config.ts'))
        $buildRequired = @($sources | Where-Object { $_.LastWriteTimeUtc -gt $distTime }).Count -gt 0
    }
    if ($buildRequired) {
        $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (-not $npm) { throw 'Node.js 22.12+ is required for the first build. Install the LTS version from nodejs.org.' }
        $node = Get-Command node.exe -ErrorAction SilentlyContinue
        if (-not $node) { throw 'Node.js 22.12+ is required. Install the LTS version from nodejs.org.' }
        $nodeVersion = & $node.Source -p 'process.versions.node'
        if ($LASTEXITCODE -ne 0 -or [version]$nodeVersion -lt [version]'22.12') { throw 'Node.js 22.12+ is required. Upgrade Node.js and run this launcher again.' }
        Push-Location -LiteralPath $frontend
        try {
            Write-Host 'Installing and building the interface...'
            Invoke-SetupCommand -Executable $npm.Source -CommandArguments @('ci', '--cache', '../.cache/npm', '--no-audit', '--no-fund') -FailureMessage 'Frontend dependency installation failed.'
            Invoke-SetupCommand -Executable $npm.Source -CommandArguments @('run', 'build') -FailureMessage 'Frontend build failed.'
        } finally { Pop-Location }
    }
    Invoke-SetupCommand -Executable $python -CommandArguments @('-m', 'backend.app.migrate') -FailureMessage 'Database migration failed. Existing data has been retained.'
    $foundPort = $false
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        try {
            $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Parse('127.0.0.1'), $port)
            $listener.Start()
            $listener.Stop()
            $foundPort = $true
            break
        } catch {
            $port++
        }
    }
    if (-not $foundPort) { throw 'No available localhost port found. Close a conflicting app or choose SCHEDULE_BUILDER_PORT in .env.' }
    $stdout = Join-Path $projectRoot "logs\server-$stamp.out.log"
    $stderr = Join-Path $projectRoot "logs\server-$stamp.err.log"
    $instance = [Guid]::NewGuid().ToString('N')
    $parentStart = (Get-Process -Id $PID).StartTime.ToUniversalTime().ToFileTimeUtc()
    $serverProcess = Start-Process -FilePath $python -ArgumentList @('scripts/serve.py', '--port', "$port", '--parent', "$PID", '--parent-start', "$parentStart", '--instance', $instance) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($serverProcess.HasExited) { throw "Server exited early. See $stderr" }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 1
            $identity = Invoke-RestMethod -Uri "http://127.0.0.1:$port/_daycraft/runtime" -TimeoutSec 1
            if ($health.status -eq 'ok' -and $health.app -eq 'schedule-builder' -and $identity.instance -eq $instance -and $identity.workspace -eq $workspaceId) { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "Startup health check timed out. See $stderr" }
    $startupMutex.ReleaseMutex()
    $ownsStartupMutex = $false
    Write-Host "Workspace ready: http://127.0.0.1:$port" -ForegroundColor Green
    Write-Host "Logs: $stdout and $stderr"
    if ($SmokeTest) {
        $page = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 5
        if ($page.StatusCode -ne 200 -or $page.Content -notmatch '<div id="root">') { throw 'Compiled frontend check failed.' }
        Write-Host 'Workspace launcher smoke test passed. Solver readiness is reported separately above.' -ForegroundColor Green
    } else {
        if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$port" }
        Write-Host 'Keep this window open. Close it, press Ctrl+C, or use Stop Daycraft.cmd to stop gracefully.'
        while (-not $serverProcess.HasExited) { Start-Sleep -Milliseconds 500 }
        if ($serverProcess.ExitCode -ne 0) { throw "Server stopped with exit code $($serverProcess.ExitCode). See $stderr" }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    $exitCode = 1
} finally {
    if ($ownsStartupMutex) { $startupMutex.ReleaseMutex() }
    if ($startupMutex) { $startupMutex.Dispose() }
    if ($serverProcess -and -not $serverProcess.HasExited -and $instance) {
        # Ask only our authenticated instance to drain requests and close SQLite.
        # Parent-handle monitoring remains the fallback if startup failed early.
        $previousErrorAction = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $python scripts/stop.py --port "$port" --instance $instance 2>&1 | ForEach-Object { $_.ToString() }
        } finally { $ErrorActionPreference = $previousErrorAction }
        if ($LASTEXITCODE -ne 0) { Write-Host 'Graceful stop was not confirmed. The parent monitor will request shutdown when this launcher exits.' -ForegroundColor Yellow }
    }
}
exit $exitCode




