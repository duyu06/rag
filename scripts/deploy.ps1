[CmdletBinding()]
param(
    [switch]$SkipModelPull,
    [switch]$SkipDemoInit,
    [switch]$SkipAgentSmoke,
    [switch]$Web,
    [switch]$NoBuild,
    [int]$StartupTimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Model = "ornith-1.5:9b"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvFile = Join-Path $RepoRoot "backend\.env"
$EnvExample = Join-Path $RepoRoot "backend\.env.example"
$OllamaApi = "http://localhost:11434"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Fail([string]$Message) {
    throw $Message
}

function Assert-LastExitCode([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        Fail "$Action failed with exit code $LASTEXITCODE"
    }
}

function Test-Http([string]$Url, [int]$TimeoutSec = 5) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-Http([string]$Name, [string]$Url, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-Http -Url $Url -TimeoutSec 5) {
            Write-Ok "$Name ready: $Url"
            return
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    Write-Host "`nDocker status:" -ForegroundColor Yellow
    & docker compose ps
    Write-Host "`nRecent service logs:" -ForegroundColor Yellow
    & docker compose logs --tail 120 qdrant backend frontend
    Fail "$Name did not become ready within $TimeoutSeconds seconds: $Url"
}

function Get-PythonMode {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return "py"
    }
    Fail "Python 3 was not found. Install Python 3 or add python/py to PATH."
}

function Invoke-Python([string[]]$Arguments) {
    if ($script:PythonMode -eq "py") {
        & py -3 @Arguments
    }
    else {
        & python @Arguments
    }
    Assert-LastExitCode "Python command: $($Arguments -join ' ')"
}

function Ensure-EnvironmentFile {
    if (-not (Test-Path $EnvFile)) {
        Copy-Item $EnvExample $EnvFile
        Write-Ok "Created backend/.env from .env.example"
    }
    else {
        Write-Ok "Using existing backend/.env"
    }

    $text = [System.IO.File]::ReadAllText($EnvFile)
    if ($text -match '(?m)^JWT_SECRET=change-me-before-production-yaoke-demo-secret\s*$') {
        $bytes = New-Object byte[] 48
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $rng.GetBytes($bytes)
        }
        finally {
            $rng.Dispose()
        }
        $secret = [Convert]::ToBase64String($bytes)
        $text = [regex]::Replace(
            $text,
            '(?m)^JWT_SECRET=change-me-before-production-yaoke-demo-secret\s*$',
            "JWT_SECRET=$secret"
        )
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($EnvFile, $text, $utf8NoBom)
        Write-Ok "Replaced demo JWT secret with a random local secret"
    }

    $modelMatch = [regex]::Match($text, '(?m)^OLLAMA_MODEL=(.+?)\s*$')
    if ($modelMatch.Success) {
        $configuredModel = $modelMatch.Groups[1].Value.Trim()
        if ($configuredModel -ne $Model) {
            Fail "backend/.env uses OLLAMA_MODEL=$configuredModel, but this release expects $Model. Update backend/.env before deployment."
        }
    }
}

function Get-OllamaTags {
    try {
        return Invoke-RestMethod -Uri "$OllamaApi/api/tags" -Method Get -TimeoutSec 8
    }
    catch {
        Fail "Ollama is not reachable at $OllamaApi. Start the Ollama desktop service, then retry. $($_.Exception.Message)"
    }
}

function Ensure-OrnithModel {
    $tags = Get-OllamaTags
    $found = $false
    foreach ($item in @($tags.models)) {
        $name = if ($item.name) { [string]$item.name } elseif ($item.model) { [string]$item.model } else { "" }
        if ($name -eq $Model) {
            $found = $true
            break
        }
    }

    if (-not $found) {
        if ($SkipModelPull) {
            Fail "$Model is not installed and -SkipModelPull was supplied."
        }
        Write-Step "Pulling $Model"
        & ollama pull $Model
        Assert-LastExitCode "ollama pull $Model"
    }
    else {
        Write-Ok "$Model is installed"
    }

    Write-Step "Loading $Model through Ollama /api/chat"
    $body = @{
        model = $Model
        messages = @(@{ role = "user"; content = "ping" })
        stream = $false
        keep_alive = "30m"
        options = @{ num_predict = 1; temperature = 0 }
    } | ConvertTo-Json -Depth 6

    try {
        $null = Invoke-RestMethod -Uri "$OllamaApi/api/chat" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 240
        Write-Ok "$Model loaded successfully"
    }
    catch {
        Fail "Ollama could not load $Model. This usually means the local model blob/runtime is broken. Error: $($_.Exception.Message)"
    }
}

try {
    Set-Location $RepoRoot
    Write-Host "yaoke P1.5 / v0.5.0 Windows deployment" -ForegroundColor White
    Write-Host "Repository: $RepoRoot"

    Write-Step "Checking prerequisites"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail "Docker was not found. Install/start Docker Desktop first."
    }
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Fail "Ollama was not found. Install/start Ollama first."
    }
    $script:PythonMode = Get-PythonMode

    & docker version *> $null
    Assert-LastExitCode "docker version"
    & docker compose version *> $null
    Assert-LastExitCode "docker compose version"
    & ollama --version *> $null
    Assert-LastExitCode "ollama --version"
    Write-Ok "Docker Desktop, Docker Compose, Ollama and Python are available"

    Write-Step "Preparing backend environment"
    Ensure-EnvironmentFile

    Write-Step "Validating Ornith runtime before Docker startup"
    Ensure-OrnithModel

    Write-Step "Starting yaoke services"
    if ($NoBuild) {
        & docker compose up -d
    }
    else {
        & docker compose up -d --build
    }
    Assert-LastExitCode "docker compose up"

    Wait-Http -Name "Backend" -Url "http://localhost:8001/api/ready" -TimeoutSeconds $StartupTimeoutSeconds
    Wait-Http -Name "Frontend" -Url "http://localhost:3000" -TimeoutSeconds $StartupTimeoutSeconds

    Write-Step "Running deployment preflight"
    Invoke-Python @("scripts/release_smoke.py")

    if (-not $SkipDemoInit) {
        Write-Step "Initializing bundled 20-document Demo corpus"
        Write-Host "The first run may download BGE embedding files into the persistent hf_cache Docker volume."
        Invoke-Python @("scripts/init_demo.py")
    }
    else {
        Write-Host "[SKIP] Demo initialization" -ForegroundColor Yellow
    }

    if (-not $SkipAgentSmoke) {
        Write-Step "Running real Local Fast Path release smoke"
        Invoke-Python @("scripts/release_smoke.py", "--agent")
    }
    else {
        Write-Host "[SKIP] Real Agent smoke" -ForegroundColor Yellow
    }

    if ($Web) {
        Write-Step "Running optional public Web Search smoke"
        Invoke-Python @("scripts/agent_smoke.py", "--agent", "--web")
    }

    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "yaoke deployment PASS" -ForegroundColor Green
    Write-Host "Web:      http://localhost:3000"
    Write-Host "Swagger:  http://localhost:8001/docs"
    Write-Host "Qdrant:   http://localhost:6333/dashboard"
    Write-Host "Debugger: http://localhost:3000/admin/agent"
    Write-Host "========================================" -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "`n[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "`nUseful diagnostics:" -ForegroundColor Yellow
    Write-Host "  docker compose ps"
    Write-Host "  docker compose logs --tail 200 backend"
    Write-Host "  ollama list"
    Write-Host "  ollama ps"
    exit 1
}
