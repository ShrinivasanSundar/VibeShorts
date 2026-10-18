# Run local live production stack on Windows
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location -Path $repoRoot

$backendEnv = "backend\.env.production"
$frontendEnv = "frontend\.env.production.local"

if (-not (Test-Path $backendEnv)) {
    Write-Error "Missing $backendEnv; configure it from its production example."
    exit 1
}
if (-not (Test-Path $frontendEnv)) {
    Write-Error "Missing $frontendEnv; configure it from its production example."
    exit 1
}

# Clear any emulator host settings
$env:FIREBASE_AUTH_EMULATOR_HOST = $null
$env:FIRESTORE_EMULATOR_HOST = $null
$env:STORAGE_EMULATOR_HOST = $null
$env:PUBSUB_EMULATOR_HOST = $null
$env:FIREBASE_STORAGE_EMULATOR_HOST = $null
$env:FIREBASE_EMULATOR_HUB = $null
$env:NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL = ""
$env:NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST = ""
$env:VIBESHORTS_LOCAL_LIVE = "1"

# Load backend/.env.production
Get-Content $backendEnv | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $idx = $line.IndexOf("=")
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
        [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
    }
}

# Load frontend/.env.production.local
Get-Content $frontendEnv | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $idx = $line.IndexOf("=")
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
        [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
    }
}

Write-Host "Running preflight integration check..." -ForegroundColor Cyan
& uv run --project backend python backend/scripts/check-integrations.py `
    --backend-env $backendEnv --frontend-env $frontendEnv --image-only

if ($LASTEXITCODE -ne 0) {
    Write-Error "Integration check failed."
    exit 1
}

if (-not (Test-Path "backend\agents\creative_director\.venv\Scripts\python.exe")) {
    Write-Error "Creative director environment missing. Run: uv sync --project backend/agents/creative_director --frozen"
    exit 1
}

if ($env:VIBESHORTS_RENDER_RUNNER -eq "docker") {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error "Docker is not on PATH."
        exit 1
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Start Docker Desktop, then retry."
        exit 1
    }
    $renderImage = if ($env:VIBESHORTS_RENDER_IMAGE) { $env:VIBESHORTS_RENDER_IMAGE } else { "vibeshorts-render:local" }
    docker image inspect $renderImage *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Build the render image: docker build -f infrastructure/Dockerfile.render -t vibeshorts-render:local ."
        exit 1
    }
}

Write-Host "Starting VibeShorts local production stack (API: 8000, Frontend: 3000)..." -ForegroundColor Green
& uv run --project backend python backend/scripts/run-local-live.py
