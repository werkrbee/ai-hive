<#
.SYNOPSIS
  Link skills-hive skills into Windows agent harnesses (Scout, Copilot, etc.).

.DESCRIPTION
  The Windows counterpart to install.sh. Creates directory JUNCTIONS (mklink /J
  equivalent) from each harness's skills dir into this repo's canonical skills/
  dir, so every harness reads the same files and you edit each skill once.

  Junctions are used (not symlinks) because they match how Scout/Copilot already
  link skills and, unlike symlinks, do not require Administrator or Developer Mode.

  For Scout specifically, this also ensures loadCopilotCliSkills is enabled in
  %USERPROFILE%\.scout\m-settings.json.

.PARAMETER Only
  Install into a single harness (scout, copilot, claude, cursor, codex, gemini).

.PARAMETER Force
  Replace an existing file/junction at the target.

.PARAMETER DryRun
  Show what would happen without changing anything.

.EXAMPLE
  .\scripts\install.ps1
.EXAMPLE
  .\scripts\install.ps1 -Only scout -DryRun
#>
[CmdletBinding()]
param(
  [string]$Only = "",
  [switch]$Force,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$Src       = Join-Path $RepoRoot "skills"

# ---------------------------------------------------------------------------
# Harness registry: label -> global skills path. Edit to add/remove harnesses.
# ---------------------------------------------------------------------------
$Harnesses = [ordered]@{
  scout   = Join-Path $env:USERPROFILE ".scout\skills"
  copilot = Join-Path $env:USERPROFILE ".copilot\skills"
  claude  = Join-Path $env:USERPROFILE ".claude\skills"
  cursor  = Join-Path $env:USERPROFILE ".cursor\skills"
  codex   = Join-Path $env:USERPROFILE ".codex\skills"
  gemini  = Join-Path $env:USERPROFILE ".gemini\skills"
  kiro    = Join-Path $env:USERPROFILE ".kiro\skills"
}

if (-not (Test-Path $Src)) {
  throw "No skills\ directory found at $Src"
}

if ($Only -and -not $Harnesses.Contains($Only)) {
  throw "Unknown harness: $Only  (known: $($Harnesses.Keys -join ', '))"
}

function Enable-ScoutSkills {
  # Ensure loadCopilotCliSkills: true in %USERPROFILE%\.scout\m-settings.json
  $settingsPath = Join-Path $env:USERPROFILE ".scout\m-settings.json"

  if (Test-Path $settingsPath) {
    $raw = Get-Content $settingsPath -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
      $json = [pscustomobject]@{}
    } else {
      $json = $raw | ConvertFrom-Json
    }
  } else {
    $json = [pscustomobject]@{}
  }

  $current = $json.PSObject.Properties['loadCopilotCliSkills']
  if ($current -and $current.Value -eq $true) {
    Write-Host "   = m-settings.json: loadCopilotCliSkills already true"
    return
  }

  if ($DryRun) {
    Write-Host "   + m-settings.json: would set loadCopilotCliSkills = true"
    return
  }

  $json | Add-Member -NotePropertyName loadCopilotCliSkills -NotePropertyValue $true -Force
  $dir = Split-Path -Parent $settingsPath
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  $json | ConvertTo-Json -Depth 32 | Set-Content -Path $settingsPath -Encoding UTF8
  Write-Host "   + m-settings.json: set loadCopilotCliSkills = true"
}

function Remove-Target($target) {
  # Remove a junction without touching the content it points at.
  $item = Get-Item $target -Force
  if ($item.LinkType) {
    cmd /c rmdir "`"$target`"" | Out-Null
  } else {
    Remove-Item $target -Recurse -Force
  }
}

function Install-Into($label, $hdir) {
  $parent = Split-Path -Parent $hdir

  # Skip harnesses that aren't installed, unless the user named one explicitly.
  if (-not $Only -and -not (Test-Path $parent)) { return }

  Write-Host "-> $label ($hdir)"
  if (-not $DryRun -and -not (Test-Path $hdir)) {
    New-Item -ItemType Directory -Path $hdir -Force | Out-Null
  }

  Get-ChildItem -Path $Src -Directory | ForEach-Object {
    $name   = $_.Name
    $srcDir = $_.FullName
    $target = Join-Path $hdir $name

    $existing = Get-Item $target -Force -ErrorAction SilentlyContinue
    if ($existing) {
      $linkTarget = @($existing.Target) | Select-Object -First 1
      if ($existing.LinkType -and $linkTarget -eq $srcDir) {
        Write-Host "   = $name (already linked)"
        return
      }
      if ($Force) {
        if (-not $DryRun) { Remove-Target $target }
      } else {
        Write-Host "   ! $name exists (skip; use -Force to replace)"
        return
      }
    }

    if ($DryRun) {
      Write-Host "   + $name (would link)"
    } else {
      New-Item -ItemType Junction -Path $target -Value $srcDir | Out-Null
      Write-Host "   + $name"
    }
  }

  if ($label -eq "scout") { Enable-ScoutSkills }
}

foreach ($label in $Harnesses.Keys) {
  if ($Only -and $Only -ne $label) { continue }
  Install-Into $label $Harnesses[$label]
}

Write-Host "Done."
