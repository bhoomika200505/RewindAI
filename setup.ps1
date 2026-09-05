<#
  RAG 2.0 - one-shot local setup for solution/ (Windows / PowerShell)

  Works on a fresh machine: installs `uv` if missing, and uv fetches the right
  Python for you - no system Python required.

  Does everything:
    1. installs uv                       (https://astral.sh/uv)
    2. creates a venv with Python 3.11   (uv downloads it if needed)
    3. installs requirements             (uv pip)
    4. creates .env from .env.example    (prompts for GROQ_API_KEY if missing)
    5. builds data\transcripts.json      (ingests a YouTube playlist)
    6. starts the server                 (uvicorn, serves the frontend at /)

  Usage (from the repo root):
    .\setup.ps1
    .\setup.ps1 "<youtube playlist URL>"
    .\setup.ps1 -PlaylistUrl "<url>" -NoServe -ForceIngest

  If PowerShell blocks the script, run once:
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>
param(
  [string]$PlaylistUrl = $env:PLAYLIST_URL,
  [switch]$NoServe,
  [switch]$ForceIngest
)

$ErrorActionPreference = "Stop"

function Log  ($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Warn ($m) { Write-Host "warning: $m" -ForegroundColor Yellow }
function Die  ($m) { Write-Host "error: $m" -ForegroundColor Red; exit 1 }

# --- locate paths ---
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $ScriptDir "solution\backend"
$DataDir     = Join-Path $ScriptDir "solution\data"
$VenvDir     = Join-Path $BackendDir ".venv"
$Transcripts = Join-Path $DataDir "transcripts.json"
$PyVersion   = "3.11"

Log "Environment: Windows / $env:PROCESSOR_ARCHITECTURE"
if (-not (Test-Path $BackendDir)) { Die "solution\backend not found next to setup.ps1." }

# --- 1. ensure uv ---
$env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
if (Get-Command uv -ErrorAction SilentlyContinue) {
  Log "uv found: $(uv --version)"
} else {
  Log "uv not installed - installing (https://astral.sh/uv)"
  powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    # last resort: installer chose a non-standard dir - locate uv.exe under the profile
    $found = Get-ChildItem -Path $env:USERPROFILE -Filter uv.exe -Recurse -ErrorAction SilentlyContinue -Depth 4 | Select-Object -First 1
    if ($found) { $env:Path = "$($found.DirectoryName);$env:Path" }
  }
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Die "uv installed but not found on PATH. Open a new PowerShell window and re-run."
  }
  Log "uv installed: $(uv --version)"
}

Set-Location $BackendDir

# --- 2. venv (uv downloads Python $PyVersion if the machine lacks it) ---
Log "Creating venv with Python $PyVersion"
uv venv --python $PyVersion $VenvDir
& (Join-Path $VenvDir "Scripts\Activate.ps1")

# --- 3. dependencies ---
Log "Installing dependencies (first run downloads torch etc - a few minutes)"
uv pip install -r requirements.txt

# --- 4. .env / GROQ_API_KEY ---
if (-not (Test-Path ".env")) {
  Log "Creating .env from .env.example"
  Copy-Item ".env.example" ".env"
}
$envLines = Get-Content ".env"
$keyLine  = $envLines | Where-Object { $_ -match '^GROQ_API_KEY=.+' -and $_ -notmatch 'your_groq_api_key_here' }
if (-not $keyLine) {
  Log "Groq API key needed (free at https://console.groq.com/keys)"
  $key = Read-Host "Paste your GROQ_API_KEY"
  if ($key) {
    $kept = $envLines | Where-Object { $_ -notmatch '^GROQ_API_KEY=' }
    ($kept + "GROQ_API_KEY=$key") | Set-Content ".env"
  } else {
    Warn "No key entered - edit solution\backend\.env before asking questions."
  }
}

# --- 5. transcripts.json (the data the app is missing) ---
$hasData = (Test-Path $Transcripts) -and ((Get-Item $Transcripts).Length -gt 0)
if ((-not $ForceIngest) -and $hasData) {
  Log "Found existing $Transcripts - skipping ingest (use -ForceIngest to rebuild)"
} else {
  if (-not $PlaylistUrl) {
    $PlaylistUrl = Read-Host "Paste a YouTube playlist URL"
  }
  if (-not $PlaylistUrl) { Die "No playlist URL. Re-run: .\setup.ps1 `"<youtube playlist URL>`"" }
  Log "Ingesting playlist into $Transcripts"
  python -m app.ingest --playlist $PlaylistUrl
  $hasData = (Test-Path $Transcripts) -and ((Get-Item $Transcripts).Length -gt 0)
  if (-not $hasData) { Die "Ingest produced no data (videos may lack captions). Check the playlist and retry." }
}

# --- 6. run ---
if (-not $NoServe) {
  Log "Starting server at http://127.0.0.1:8000  (Ctrl-C to stop)"
  uvicorn app.main:app --reload
} else {
  Log "Setup complete. Start the server with:"
  Write-Host "    cd solution\backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload"
}