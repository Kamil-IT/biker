<#
.SYNOPSIS
  Deploys biker to GCP Cloud Run: backend (FastAPI + Chromium) and frontend (nginx) as two services
  in europe-central2, both against Cloud SQL biker-pg. Run by hand from the developer machine (TODO-030).

.DESCRIPTION
  One-time prerequisites (see README § Deploy to GCP):
    gcloud auth login; APIs run / artifactregistry / secretmanager / sqladmin enabled;
    Artifact Registry repo "biker" (docker, europe-central2); service account biker-run with
    roles/cloudsql.client and secretmanager.secretAccessor on the secrets anthropic-api-key and db-password;
    gcloud auth configure-docker europe-central2-docker.pkg.dev.
  Nothing secret is in the repo or the images: the key and the DB password reach the backend only as
  Secret Manager references (ANTHROPIC_API_KEY, PGPASSWORD).
  Who may call the services is NOT decided here: this script never touches the IAM policy, so the
  one-time "public" binding (README § Deploy to GCP) survives every redeploy and a fresh service starts
  closed (authenticated callers only).

.EXAMPLE
  .\scripts\deploy.ps1                     # build + push + deploy both services
  .\scripts\deploy.ps1 -Only backend       # backend only (frontend keeps its BACKEND_URL)
  .\scripts\deploy.ps1 -Only frontend      # frontend only, pointed at the deployed backend
  .\scripts\deploy.ps1 -Tag v1             # explicit image tag instead of the git short sha
#>
[CmdletBinding()]
param(
    [string]$Project = 'biker-engine-prod',
    [string]$Region = 'europe-central2',
    [string]$SqlInstance = 'biker-engine-prod:europe-central2:biker-pg',
    [ValidateSet('all', 'backend', 'frontend')][string]$Only = 'all',
    [string]$Tag
)

$root = Split-Path -Parent $PSScriptRoot          # scripts\ -> repo root
$repo = "$Region-docker.pkg.dev/$Project/biker"
$sa = "biker-run@$Project.iam.gserviceaccount.com"

if (-not $Tag) {
    $Tag = (git -C $root rev-parse --short HEAD).Trim()
    if (git -C $root status --porcelain -- backend frontend) { $Tag = "$Tag-dirty" }
}

function Invoke-Step([string]$What, [scriptblock]$Cmd) {
    Write-Host "==> $What" -ForegroundColor Cyan
    & $Cmd
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

function Get-ServiceUrl([string]$Service) {
    # `services list --filter` is silent for a missing service; `describe` would write to stderr, which PS 5.1 reports as an error.
    $url = gcloud run services list --project $Project --region $Region --filter "metadata.name=$Service" --format 'value(status.url)'
    if ($url) { return "$url".Trim() }
    return $null
}

if ($Only -in 'all', 'backend') {
    $img = "$repo/backend:$Tag"
    Invoke-Step "docker build backend -> $img" { docker build -t $img "$root\backend" }
    Invoke-Step "docker push backend" { docker push $img }
    Invoke-Step "gcloud run deploy biker-backend" {
        gcloud run deploy biker-backend --project $Project --region $Region --image $img `
            --service-account $sa `
            --add-cloudsql-instances $SqlInstance `
            --set-env-vars "DATABASE_URL=postgresql+psycopg://biker@/biker?host=/cloudsql/$SqlInstance,PLAYWRIGHT_HEADLESS=true,BROWSER_MAX_CONCURRENCY=2" `
            --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,PGPASSWORD=db-password:latest" `
            --port 8000 --cpu 2 --memory 2Gi --concurrency 20 --timeout 600 `
            --min-instances 0 --max-instances 2 --cpu-boost `
            --quiet
    }
}

$backendUrl = Get-ServiceUrl 'biker-backend'
if (-not $backendUrl) { throw 'biker-backend is not deployed yet; run without -Only frontend first' }

if ($Only -in 'all', 'frontend') {
    $img = "$repo/frontend:$Tag"
    Invoke-Step "docker build frontend -> $img" { docker build -t $img "$root\frontend" }
    Invoke-Step "docker push frontend" { docker push $img }
    Invoke-Step "gcloud run deploy biker-frontend" {
        gcloud run deploy biker-frontend --project $Project --region $Region --image $img `
            --service-account $sa `
            --set-env-vars "BACKEND_URL=$backendUrl" `
            --port 8080 --cpu 1 --memory 256Mi --concurrency 80 --timeout 600 `
            --min-instances 0 --max-instances 2 `
            --quiet
    }
}

$frontendUrl = Get-ServiceUrl 'biker-frontend'
Write-Host ''
Write-Host "Image tag: $Tag"
Write-Host "Backend:   $backendUrl"
Write-Host "Frontend:  $frontendUrl   <- open this one" -ForegroundColor Green
