<#
.SYNOPSIS
  Render a rules-hive ruleset into each harness's native instruction file (Windows).
.PARAMETER Ruleset
  Ruleset under rules/ (default: queen-charter).
.PARAMETER Harness
  One or more harnesses (default: agents, claude-code, cursor, github-copilot, gemini-cli).
.PARAMETER Dir
  Project directory to write into (default: current directory).
.EXAMPLE
  .\scripts\install.ps1 -Dir C:\path\to\project
#>
[CmdletBinding()]
param(
  [string]$Ruleset = "queen-charter",
  [string[]]$Harness = @(),
  [string]$Dir = "."
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Src = Join-Path $RepoRoot "rules\$Ruleset\AGENTS.md"
if (-not (Test-Path $Src)) { throw "ruleset not found: $Src" }
$content = Get-Content $Src -Raw

$HouseRoot = Split-Path -Parent (Split-Path -Parent $RepoRoot)
$Registry = Get-Content (Join-Path $HouseRoot "harnesses.json") -Raw | ConvertFrom-Json
$Targets = @{}
foreach ($h in $Registry.harnesses) {
  if ($h.surfaces.rules.windows_default_order -and
      (-not ($h.surfaces.rules.project -is [string]) -or -not $h.surfaces.rules.project)) {
    throw "Harness '$($h.id)' needs a project rules path in harnesses.json"
  }
  if ($h.surfaces.rules.project) { $Targets[$h.id] = $h.surfaces.rules.project }
}
if (-not $Harness.Count) {
  $Harness = @($Registry.harnesses | Where-Object { $_.surfaces.rules.windows_default_order } |
               Sort-Object { $_.surfaces.rules.windows_default_order } | ForEach-Object { $_.id })
}
function Rel($h) {
  if ($Targets.ContainsKey($h)) { return $Targets[$h].Replace('{name}', $Ruleset) }
  return $null
}

foreach ($h in $Harness) {
  $rel = Rel $h
  if (-not $rel) { Write-Error "unknown harness: $h"; continue }
  $target = Join-Path $Dir $rel
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
  if ($h -eq "cursor") {
    "---`ndescription: $Ruleset`nalwaysApply: true`n---`n`n$content" | Set-Content -Path $target -Encoding UTF8
  } elseif ($h -eq "devin-desktop") {
    "---`ntrigger: always_on`n---`n`n$content" | Set-Content -Path $target -Encoding UTF8
  } else {
    $content | Set-Content -Path $target -Encoding UTF8
  }
  Write-Host "wrote: $target"
}
Write-Host "done."
