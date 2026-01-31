<#
.SYNOPSIS
    Infinite Loop PowerShell Bot (Based on User's Manual)
    
.DESCRIPTION
    This script implements the requested logic:
    1. Loop through all workflows.
    2. Trigger them.
    3. Wait 5.5 hours.
    4. Repeat (kill old, start new).
#>

param (
    [string]$token = $env:GH_PAT,
    [string]$repo = $env:GITHUB_REPOSITORY
)

# 1. Setup
if (-not $token -or -not $repo) {
    Write-Host "Error: Missing Token or Repo" -ForegroundColor Red
    exit 1
}

$owner = $repo.Split('/')[0]
$repoName = $repo.Split('/')[1]
$baseUri = "https://api.github.com/repos/$owner/$repoName"

$headers = @{
    "Authorization" = "token $token"
    "Accept"        = "application/vnd.github.v3+json"
}

# Function to Trigger a Workflow
function Trigger-Workflow {
    param ($fileName, $id)
    Write-Host " [Triggering] $fileName..." -NoNewline
    
    $body = @{ ref = "main" } | ConvertTo-Json
    
    try {
        Invoke-RestMethod -Uri "$baseUri/actions/workflows/$id/dispatches" `
                          -Method Post `
                          -Headers $headers `
                          -Body $body `
                          -ErrorAction Stop
        Write-Host " OK" -ForegroundColor Green
    }
    catch {
        Write-Host " Failed ($($_.Exception.Message))" -ForegroundColor Red
        # Fallback to repository_dispatch
        try {
            $dispBody = @{ event_type = "keepalive_trigger" } | ConvertTo-Json
            Invoke-RestMethod -Uri "$baseUri/dispatches" `
                              -Method Post `
                              -Headers $headers `
                              -Body $dispBody `
                              -ErrorAction Stop
            Write-Host "  -> Fallback Dispatch Sent" -ForegroundColor Cyan
        } catch {}
    }
}

# Main Logic
Write-Host "============================"
Write-Host "   INFINITE LOOP BOT (PS)   "
Write-Host "============================"

# A. Initial Trigger (User Workflows ONLY - not myself!)
Write-Host "[1] Initial Trigger: Starting your workflows..."
try {
    $wfResponse = Invoke-RestMethod -Uri "$baseUri/actions/workflows" -Method Get -Headers $headers
    $workflows = $wfResponse.workflows
} catch {
    Write-Host "Error listing workflows: $($_.Exception.Message)"
    exit 1
}

foreach ($wf in $workflows) {
    # Skip the loop manager itself to avoid duplication!
    if ($wf.name -like "*Infinite Loop Manager*") {
        Write-Host " [Skipping] $($wf.name) (that's me!)" -ForegroundColor Yellow
        continue
    }
    
    if ($wf.state -eq "active") {
        Trigger-Workflow -fileName $wf.name -id $wf.id
    }
}

# B. Wait
$hours = 5.5
$seconds = $hours * 3600
Write-Host ""
Write-Host "[2] Waiting $hours hours ($seconds seconds)..."
Write-Host "    (Bot will sleep now. Your workflows are running!)"

Start-Sleep -Seconds $seconds

# C. After Wait: Trigger ALL (including myself for the next cycle)
Write-Host ""
Write-Host "[3] Time's Up! Refreshing ALL workflows (including loop)..."

try {
    $wfResponse = Invoke-RestMethod -Uri "$baseUri/actions/workflows" -Method Get -Headers $headers
    $workflows = $wfResponse.workflows
} catch {
    Write-Host "Error listing workflows: $($_.Exception.Message)"
    exit 1
}

foreach ($wf in $workflows) {
    # ONLY trigger the loop manager to renew the cycle
    # The new manager instance will trigger the user workflows when it starts (Step A)
    if ($wf.name -like "*Infinite Loop Manager*") {
        Trigger-Workflow -fileName $wf.name -id $wf.id
    }
}

Write-Host "============================"
Write-Host " Cycle Complete. Exiting to let new jobs take over."
Write-Host "============================"
