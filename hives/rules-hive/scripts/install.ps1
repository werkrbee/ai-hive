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
  [string[]]$Harness = @("agents","claude-code","cursor","github-copilot","gemini-cli"),
  [string]$Dir = "."
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Src = Join-Path $RepoRoot "rules\$Ruleset\AGENTS.md"
if (-not (Test-Path $Src)) { throw "ruleset not found: $Src" }
$content = Get-Content $Src -Raw

function Rel($h) {
  switch ($h) {
    { $_ -in "agents","opencode","codex","kiro","databricks-genie-code","snowflake-cortex-code" } { "AGENTS.md" }
    "claude-code"    { "CLAUDE.md" }
    "cursor"         { ".cursor\rules\$Ruleset.mdc" }
    "github-copilot" { ".github\copilot-instructions.md" }
    "gemini-cli"     { "GEMINI.md" }
    "goose"          { ".goosehints" }
    default          { $null }
  }
}

foreach ($h in $Harness) {
  $rel = Rel $h
  if (-not $rel) { Write-Error "unknown harness: $h"; continue }
  $target = Join-Path $Dir $rel
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
  if ($h -eq "cursor") {
    "---`ndescription: $Ruleset`nalwaysApply: true`n---`n`n$content" | Set-Content -Path $target -Encoding UTF8
  } else {
    $content | Set-Content -Path $target -Encoding UTF8
  }
  Write-Host "wrote: $target"
}
Write-Host "done."
