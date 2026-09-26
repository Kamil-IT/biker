<#
.SYNOPSIS
  Deploys biker to GCP Cloud Run: backend (FastAPI + Chromium), frontend (nginx) and the on-demand
  OLX / Decathlon / Allegro searcher (claude CLI + Chromium, TODO-031/032/033) as three services in
  europe-central2, all against Cloud SQL biker-pg. Run by hand from the developer machine (TODO-030).

.DESCRIPTION
  One-time prerequisites (see README § Deploy to GCP):
    gcloud auth login; APIs run / artifactregistry / secretmanager / sqladmin enabled;
    Artifact Registry repo "biker" (docker, europe-central2); service account biker-run with
    roles/cloudsql.client and secretmanager.secretAccessor on the secrets anthropic-api-key, db-password,
    searcher-api-key and claude-code-oauth-token; gcloud auth configure-docker europe-central2-docker.pkg.dev.
  Nothing secret is in the repo or the images: the key and the DB password reach the backend only as
  Secret Manager references (ANTHROPIC_API_KEY, PGPASSWORD); the searcher gets PGPASSWORD, SEARCHER_API_KEY and
  CLAUDE_CODE_OAUTH_TOKEN the same way, and the backend reaches it with SEARCHER_URL + the same SEARCHER_API_KEY.
  Order matters on a first deploy: searcher, then backend (which needs the searcher's URL), then frontend.
  Who may call the services is NOT decided here: this script never touches the IAM policy, so the
  one-time "public" binding (README § Deploy to GCP) survives every redeploy and a fresh service starts
  closed (authenticated callers only).

.EXAMPLE
  .\scripts\deploy.ps1                     # build + push + deploy both services
  .\scripts\deploy.ps1 -Only backend       # backend only (frontend keeps its BACKEND_URL)
  .\scripts\deploy.ps1 -Only frontend      # frontend only, pointed at the deployed backend
  .\scripts\deploy.ps1 -Only searcher      # the OLX/Decathlon/Allegro searcher only (the backend keeps its SEARCHER_URL)
  .\scripts\deploy.ps1 -Tag v1             # explicit image tag instead of the git short sha
#>
[CmdletBinding()]
param(
    [string]$Project = 'biker-engine-prod',
    [string]$Region = 'europe-central2',
    [string]$SqlInstance = 'biker-engine-prod:europe-central2:biker-pg',
    [ValidateSet('all', 'backend', 'frontend', 'searcher')][string]$Only = 'all',
    [string]$Tag
)

$root = Split-Path -Parent $PSScriptRoot          # scripts\ -> repo root
$repo = "$Region-docker.pkg.dev/$Project/biker"
$sa = "biker-run@$Project.iam.gserviceaccount.com"

if (-not $Tag) {
    $Tag = (git -C $root rev-parse --short HEAD).Trim()
    if (git -C $root status --porcelain -- backend frontend searcher) { $Tag = "$Tag-dirty" }
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

$dbUrl = "postgresql+psycopg://biker@/biker?host=/cloudsql/$SqlInstance"

if ($Only -in 'all', 'searcher') {
    # One CLI run + one Chromium per 2 GiB instance (--concurrency 1), scale to zero. Two instances because the
    # UI's "Nowe" button fires the Decathlon and Allegro searches together (backend SEARCHER_MAX_INFLIGHT = 2,
    # TODO-033): the second search gets its own instance; a third concurrent search hits Cloud Run's 429, which
    # the backend maps to 503 busy. A search is minutes, hence the 900 s timeout (the backend waits at most
    # SEARCHER_TIMEOUT = 600 s).
    $img = "$repo/searcher:$Tag"
    Invoke-Step "docker build searcher -> $img" { docker build -t $img "$root\searcher" }
    Invoke-Step "docker push searcher" { docker push $img }
    Invoke-Step "gcloud run deploy biker-searcher" {
        gcloud run deploy biker-searcher --project $Project --region $Region --image $img `
            --service-account $sa `
            --add-cloudsql-instances $SqlInstance `
            --set-env-vars "DATABASE_URL=$dbUrl,PLAYWRIGHT_HEADLESS=true" `
            --set-secrets "PGPASSWORD=db-password:latest,SEARCHER_API_KEY=searcher-api-key:latest,CLAUDE_CODE_OAUTH_TOKEN=claude-code-oauth-token:latest" `
            --port 8100 --cpu 2 --memory 2Gi --concurrency 1 --timeout 900 `
            --min-instances 0 --max-instances 2 --cpu-boost `
            --quiet
    }
}

$searcherUrl = Get-ServiceUrl 'biker-searcher'

if ($Only -in 'all', 'backend') {
    # Without a deployed searcher the backend still works; the three searcher proxies
    # (POST /v1/bike/used/search, /v1/bike/decathlon/search, /v1/bike/allegro/search) then answer 503.
    $env = "DATABASE_URL=$dbUrl,PLAYWRIGHT_HEADLESS=true,BROWSER_MAX_CONCURRENCY=2"
    $secrets = "ANTHROPIC_API_KEY=anthropic-api-key:latest,PGPASSWORD=db-password:latest"
    if ($searcherUrl) {
        $env += ",SEARCHER_URL=$searcherUrl"
        $secrets += ",SEARCHER_API_KEY=searcher-api-key:latest"
    } else {
        Write-Warning 'biker-searcher is not deployed: the backend is deployed without SEARCHER_URL (the OLX / Decathlon / Allegro searches answer 503)'
    }
    $img = "$repo/backend:$Tag"
    Invoke-Step "docker build backend -> $img" { docker build -t $img "$root\backend" }
    Invoke-Step "docker push backend" { docker push $img }
    Invoke-Step "gcloud run deploy biker-backend" {
        gcloud run deploy biker-backend --project $Project --region $Region --image $img `
            --service-account $sa `
            --add-cloudsql-instances $SqlInstance `
            --set-env-vars $env `
            --set-secrets $secrets `
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
Write-Host "Searcher:  $(if ($searcherUrl) { $searcherUrl } else { '(not deployed)' })"
Write-Host "Backend:   $backendUrl"
Write-Host "Frontend:  $frontendUrl   <- open this one" -ForegroundColor Green
