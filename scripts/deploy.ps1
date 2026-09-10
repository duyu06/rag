[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$SkipModelPull,
    [switch]$SkipDemoInit,
    [switch]$SkipSmoke,
    [switch]$Web,
    [switch]$OpenBrowser,
    [int]$StartupTimeoutSeconds = 240
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$env:PYTHONUTF8 = '1'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing command '$Name'. $Hint"
    }
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments, [string]$Label) {
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Wait-Http([string]$Url, [string]$Name, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 4
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                Write-Ok "$Name ready: $Url"
                return
            }
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become ready within ${TimeoutSeconds}s. Last error: $lastError"
}

function Ensure-OllamaApi {
    try {
        Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 4 | Out-Null
        Write-Ok 'Ollama API reachable on localhost:11434'
        return
    }
    catch {
        Write-Host '[INFO] Ollama API is not reachable; trying `ollama serve`...' -ForegroundColor Yellow
    }

    try {
        Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    }
    catch {
        throw 'Ollama is installed but could not be started. Start Ollama manually, then rerun this script.'
    }

    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        try {
            Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 3 | Out-Null
            Write-Ok 'Ollama API started on localhost:11434'
            return
        }
        catch { }
    }
    throw 'Ollama API is still unavailable at http://localhost:11434. Start Ollama manually and retry.'
}

function Get-PythonRunner {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ File = 'python'; Prefix = @() }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ File = 'py'; Prefix = @('-3') }
    }
    throw 'Python 3 was not found. Install Python 3 and ensure `python` or `py` is available in PATH.'
}

function Invoke-PythonScript([hashtable]$Runner, [string[]]$Arguments, [string]$Label) {
    $allArgs = @($Runner.Prefix) + $Arguments
    Invoke-Native $Runner.File $allArgs $Label
}

function Show-Diagnostics {
    Write-Host "`n--- docker compose ps ---" -ForegroundColor Yellow
    try { & docker compose ps } catch { }
    Write-Host "`n--- backend logs (last 120 lines) ---" -ForegroundColor Yellow
    try { & docker compose logs --tail=120 backend } catch { }
    Write-Host "`n--- frontend logs (last 80 lines) ---" -ForegroundColor Yellow
    try { & docker compose logs --tail=80 frontend } catch { }
    Write-Host "`n--- qdrant logs (last 80 lines) ---" -ForegroundColor Yellow
    try { & docker compose logs --tail=80 qdrant } catch { }
}

trap {
    Write-Host "`n[FAILED] $($_.Exception.Message)" -ForegroundColor Red
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Show-Diagnostics
    }
    exit 1
}

Write-Host 'yaoke deployment assistant' -ForegroundColor White
Write-Host 'Windows + Docker Desktop + local Ollama' -ForegroundColor DarkGray

Write-Step '1/7 Preflight'
Assert-Command 'docker' 'Install/start Docker Desktop first.'
Assert-Command 'ollama' 'Install Ollama for Windows first.'
Invoke-Native 'docker' @('version') 'Docker engine check'
Invoke-Native 'docker' @('compose', 'version') 'Docker Compose check'
Ensure-OllamaApi
$python = Get-PythonRunner
Write-Ok "Repository: $Root"

Write-Step '2/7 Environment configuration'
$envPath = Join-Path $Root 'backend\.env'
$examplePath = Join-Path $Root 'backend\.env.example'
if (-not (Test-Path $envPath)) {
    Copy-Item $examplePath $envPath
    $raw = Get-Content $envPath -Raw
    $secret = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
    $raw = [regex]::Replace($raw, '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$secret")
    Set-Content -Path $envPath -Value $raw -Encoding UTF8
    Write-Ok 'Created backend/.env and generated a non-default JWT secret'
}
else {
    Write-Ok 'Using existing backend/.env (not overwritten)'
}

$envText = Get-Content $envPath -Raw
$modelMatch = [regex]::Match($envText, '(?m)^OLLAMA_MODEL=(.+)$')
$model = if ($modelMatch.Success) { $modelMatch.Groups[1].Value.Trim() } else { 'ornith-1.5:9b' }
if ($model -ne 'ornith-1.5:9b') {
    Write-Host "[WARN] backend/.env uses OLLAMA_MODEL=$model (project default is ornith-1.5:9b)" -ForegroundColor Yellow
}
if ($envText -match '(?m)^JWT_SECRET=change-me-before-production-yaoke-demo-secret\s*$') {
    Write-Host '[WARN] Existing backend/.env still uses the demo JWT secret. Change it before exposing the service publicly.' -ForegroundColor Yellow
}

Write-Step "3/7 Ollama model: $model"
$modelList = (& ollama list 2>&1 | Out-String)
$escapedModel = [regex]::Escape($model)
if ($modelList -notmatch "(?m)^$escapedModel\s") {
    if ($SkipModelPull) {
        throw "Ollama model '$model' is not installed and -SkipModelPull was specified."
    }
    Write-Host "[INFO] Pulling $model. This may take a while..." -ForegroundColor Yellow
    Invoke-Native 'ollama' @('pull', $model) "ollama pull $model"
}
Write-Ok "Ollama model available: $model"

Write-Step '4/7 Build and start Docker Compose'
if ($SkipBuild) {
    Invoke-Native 'docker' @('compose', 'up', '-d', '--remove-orphans') 'docker compose up'
}
else {
    Invoke-Native 'docker' @('compose', 'up', '-d', '--build', '--remove-orphans') 'docker compose up --build'
}
& docker compose ps

Write-Step '5/7 Wait for services'
Wait-Http 'http://localhost:6333/healthz' 'Qdrant' $StartupTimeoutSeconds
Wait-Http 'http://localhost:8001/api/ready' 'Backend' $StartupTimeoutSeconds
Wait-Http 'http://localhost:3000' 'Frontend' $StartupTimeoutSeconds
Invoke-PythonScript $python @('scripts/check_demo.py') 'preflight smoke'

if (-not $SkipDemoInit) {
    Write-Step '6/7 Initialize bundled Demo corpus (20 documents)'
    Write-Host '[INFO] First initialization may download the BGE embedding model.' -ForegroundColor Yellow
    Invoke-PythonScript $python @('scripts/init_demo.py') 'Demo initialization'
}
else {
    Write-Step '6/7 Demo initialization skipped'
}

if (-not $SkipSmoke) {
    Write-Step '7/7 Runtime acceptance tests'
    Invoke-PythonScript $python @('scripts/demo_smoke.py', '--retrieval') 'Retrieval/RBAC smoke'
    Invoke-PythonScript $python @('scripts/agent_smoke.py', '--agent') 'Ornith Agent smoke'
    if ($Web) {
        Invoke-PythonScript $python @('scripts/agent_smoke.py', '--agent', '--web') 'Agent Web Search smoke'
    }
    else {
        Write-Host '[INFO] Public Web Search smoke skipped. Rerun with -Web to include DDGS.' -ForegroundColor DarkGray
    }
}
else {
    Write-Step '7/7 Runtime smoke skipped'
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host 'yaoke deployment: PASS' -ForegroundColor Green
Write-Host 'Web:            http://localhost:3000'
Write-Host 'Swagger:        http://localhost:8001/docs'
Write-Host 'Qdrant:         http://localhost:6333/dashboard'
Write-Host 'Agent Debugger: http://localhost:3000/admin/agent'
Write-Host '========================================' -ForegroundColor Green

if ($OpenBrowser) {
    Start-Process 'http://localhost:3000'
}
