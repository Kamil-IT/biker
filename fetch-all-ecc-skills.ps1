# Download ALL 449 ECC skills from GitHub

`$skillsDir = ".\.claude\skills"
`$eccRepo = "affaan-m/ECC"
`$branch = "main"
`$baseUrl = "https://raw.githubusercontent.com/`$eccRepo/`$branch/skills"

# Create skills directory
if (-not (Test-Path `$skillsDir)) {
    New-Item -ItemType Directory -Path `$skillsDir -Force | Out-Null
}

Write-Host "Fetching ECC skills list..."
`$apiUrl = "https://api.github.com/repos/`$eccRepo/git/trees/`$branch?recursive=1"
`$response = Invoke-RestMethod -Uri `$apiUrl -TimeoutSec 30

`$skillFiles = `$response.tree | Where-Object { `$_.path -like 'skills/*.md' -and `$_.type -eq 'blob' } | Select-Object -ExpandProperty path

`$totalSkills = @(`$skillFiles).Count
Write-Host "Found `$totalSkills skills. Starting download..."

`$downloaded = 0
`$failed = 0

foreach (`$skillPath in `$skillFiles) {
    `$skillName = Split-Path -Leaf `$skillPath
    `$outputPath = Join-Path `$skillsDir `$skillName
    `$fileUrl = "`$baseUrl/`$skillName"

    try {
        Invoke-WebRequest -Uri `$fileUrl -OutFile `$outputPath -TimeoutSec 10 -ErrorAction Stop | Out-Null
        `$downloaded++
        Write-Host "OK: `$skillName"
    }
    catch {
        `$failed++
        Write-Host "FAIL: `$skillName"
    }

    # Small delay to avoid rate limiting
    Start-Sleep -Milliseconds 100
}

Write-Host ""
Write-Host "Download complete!"
Write-Host "Downloaded: `$downloaded"
Write-Host "Failed: `$failed"
`$count = (Get-ChildItem `$skillsDir -Filter '*.md' | Measure-Object).Count
Write-Host "Total skills in directory: `$count"
