# Bring up everything the API test suite needs locally: Postgres, Redis, Anvil.
#
# Why this exists. The suite's fixtures skip when a dependency is unreachable,
# so a missing dependency does not fail the run, it quietly shrinks it. On
# 2026-08-15 a workstation cleanup removed Docker Desktop, which had been
# providing Postgres and Redis. Nothing broke loudly. The suite kept exiting
# zero while running none of its 667 tests, and a separate 19 chain and rate
# limit tests had been skipping before that for the same reason.
#
# A dependency with a fallback path is more dangerous to remove than one
# without, because the fallback hides the removal. So this script exists to make
# the full environment one command, and `-Status` exists to answer "is the suite
# actually checking anything" without having to read a progress line for the
# letter s.
#
# These run as plain processes rather than containers. What the tests need is a
# database, a cache and a chain node, not a container runtime, and every layer
# in between is another thing that can disappear without saying so.
#
# Usage:
#   pwsh scripts/local-dev.ps1            start everything, installing if needed
#   pwsh scripts/local-dev.ps1 -Stop      stop everything
#   pwsh scripts/local-dev.ps1 -Status    report what is and is not answering

param(
    [switch]$Stop,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path $PSScriptRoot -Parent

# --- Postgres ---------------------------------------------------------------
$PgRoot = "$env:LOCALAPPDATA\agoreum-pg"
$PgBin = "$PgRoot\pgsql\bin"
$PgData = "$PgRoot\data"
$PgLog = "$PgRoot\pg.log"
$PgPort = 55432
$PgUser = 'agoreum'
$PgDb = 'agoreum'
# Matches apps/api/.env. This cluster holds nothing but test fixtures and listens
# on loopback only, so the password is a formality. Writing it in the open is
# more honest than implying it protects something.
$PgPassword = 'agoreum_local_dev_only'
$PgVersion = '17.6-1'
$PgUrl = "https://get.enterprisedb.com/postgresql/postgresql-$PgVersion-windows-x64-binaries.zip"

# --- Redis ------------------------------------------------------------------
$RedisRoot = "$env:LOCALAPPDATA\agoreum-redis"
$RedisPort = 6379
$RedisUrl = 'https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip'

# --- Anvil ------------------------------------------------------------------
# Foundry is installed but not on PATH on this machine, so it is located rather
# than assumed. The chain tests read a fixture built against a genuinely
# deployed contract, not a mock, which is why the node has to be running before
# the fixture can be built.
$AnvilPort = 8545
$AnvilCandidates = @(
    "$env:USERPROFILE\foundry\anvil.exe",
    "$env:USERPROFILE\.foundry\bin\anvil.exe"
)
$Anvil = $AnvilCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

function Test-Port([int]$Port) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect('127.0.0.1', $Port)
        $c.Close()
        return $true
    } catch { return $false }
}

function Write-State([string]$Name, [bool]$Up, [string]$Detail) {
    $mark = if ($Up) { 'up  ' } else { 'DOWN' }
    "{0}  {1,-9} {2}" -f $mark, $Name, $Detail
}

if ($Status) {
    Write-State 'postgres' (Test-Port $PgPort) "127.0.0.1:$PgPort"
    Write-State 'redis' (Test-Port $RedisPort) "127.0.0.1:$RedisPort"
    Write-State 'anvil' (Test-Port $AnvilPort) "127.0.0.1:$AnvilPort"
    if (-not ((Test-Port $PgPort) -and (Test-Port $RedisPort) -and (Test-Port $AnvilPort))) {
        ''
        'Something is down. The suite will SKIP the tests that need it and still exit 0.'
    }
    return
}

if ($Stop) {
    if (Test-Path "$PgBin\pg_ctl.exe") { & "$PgBin\pg_ctl.exe" -D $PgData -m fast stop }
    Get-Process redis-server, anvil -ErrorAction SilentlyContinue | Stop-Process -Force
    'stopped'
    return
}

# --- Install and start Postgres ---------------------------------------------
# Only bin, lib and share are extracted. The archive also carries pgAdmin, a
# desktop application with no use here and most of the unpacked size.
if (-not (Test-Path "$PgBin\postgres.exe")) {
    "installing PostgreSQL $PgVersion"
    $zipPath = "$env:TEMP\agoreum-pg-$PgVersion.zip"
    if (-not (Test-Path $zipPath)) { Invoke-WebRequest -Uri $PgUrl -OutFile $zipPath -UseBasicParsing }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName -notmatch '^pgsql/(bin|lib|share)/' -or $entry.Name -eq '') { continue }
            $out = Join-Path $PgRoot $entry.FullName.Replace('/', '\')
            $dir = Split-Path $out -Parent
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $out, $true)
        }
    } finally {
        $archive.Dispose()
    }
}

if (-not (Test-Path "$PgData\PG_VERSION")) {
    'initialising the cluster'
    $pwFile = "$env:TEMP\agoreum-pg-init.txt"
    Set-Content -Path $pwFile -Value $PgPassword -NoNewline -Encoding ascii
    try {
        & "$PgBin\initdb.exe" -D $PgData -U $PgUser --pwfile=$pwFile -E UTF8 --locale=C | Out-Null
    } finally {
        Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Port $PgPort)) {
    & "$PgBin\pg_ctl.exe" -D $PgData -l $PgLog -o "-p $PgPort -c listen_addresses=127.0.0.1" -w start | Out-Null
}

$env:PGPASSWORD = $PgPassword
$dbExists = & "$PgBin\psql.exe" -h 127.0.0.1 -p $PgPort -U $PgUser -d postgres -tAc `
    "SELECT 1 FROM pg_database WHERE datname = '$PgDb'"
if ($dbExists -ne '1') {
    & "$PgBin\createdb.exe" -h 127.0.0.1 -p $PgPort -U $PgUser $PgDb
    "created database $PgDb"
}

# --- Install and start Redis ------------------------------------------------
if (-not (Test-Path "$RedisRoot\redis-server.exe")) {
    'installing Redis'
    $redisZip = "$env:TEMP\agoreum-redis.zip"
    if (-not (Test-Path $redisZip)) { Invoke-WebRequest -Uri $RedisUrl -OutFile $redisZip -UseBasicParsing }
    Expand-Archive -Path $redisZip -DestinationPath $RedisRoot -Force
}

if (-not (Test-Port $RedisPort)) {
    # No persistence: this instance holds rate limit counters and nothing that
    # should outlive a reboot.
    Start-Process -FilePath "$RedisRoot\redis-server.exe" `
        -ArgumentList "--port $RedisPort --bind 127.0.0.1 --save ''" -WindowStyle Hidden
}

# --- Start Anvil and build the chain fixture --------------------------------
if (-not $Anvil) {
    'anvil not found. Install Foundry, then re-run. The chain tests will skip until then.'
} elseif (-not (Test-Port $AnvilPort)) {
    Start-Process -FilePath $Anvil `
        -ArgumentList "--port $AnvilPort --chain-id 31337 --silent" -WindowStyle Hidden
    for ($i = 0; $i -lt 30 -and -not (Test-Port $AnvilPort); $i++) { Start-Sleep -Seconds 1 }

    # The fixture records a real deployment on this node, so it is rebuilt
    # whenever the node is, and is meaningless against a different one.
    if (Test-Port $AnvilPort) {
        Push-Location $RepoRoot
        try {
            $env:PATH = "$(Split-Path $Anvil -Parent);$env:PATH"
            python scripts/anvil_fixture.py | Select-Object -Last 1
        } finally {
            Pop-Location
        }
    }
}

''
Write-State 'postgres' (Test-Port $PgPort) "127.0.0.1:$PgPort"
Write-State 'redis' (Test-Port $RedisPort) "127.0.0.1:$RedisPort"
Write-State 'anvil' (Test-Port $AnvilPort) "127.0.0.1:$AnvilPort"
''
'Then:  cd apps/api; python -m alembic upgrade head; python -m app.cli seed'
