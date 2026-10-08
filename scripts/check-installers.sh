#!/usr/bin/env bash
# Installer checks. Used by CI; run locally from the repo root before shipping.
# 1. Syntax: every *.sh parses (bash -n), every *.py parses, and every *.ps1 parses with the
#    PowerShell language parser (needs pwsh; required in CI, skipped locally if missing).
# 2. Smoke: each hive installer runs end to end in a throwaway HOME and project dir, and
#    the workflows-hive engine resumes a run after a simulated crash.
#    Shell installers do a real install; Python installers run with --dry-run.
# Exit non-zero on any failure.
set -uo pipefail

root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1

fail=0
pass() { echo "ok    $1"; }
flunk() { echo "FAIL  $1"; fail=1; }

echo "== syntax"
while IFS= read -r -d '' f; do
  if bash -n "$f"; then pass "$f"; else flunk "$f"; fi
done < <(find . -type f -name '*.sh' -not -path './.git/*' -print0)

while IFS= read -r -d '' f; do
  if python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])' "$f"; then
    pass "$f"
  else
    flunk "$f"
  fi
done < <(find . -type f -name '*.py' -not -path './.git/*' -print0)

# shellcheck disable=SC2016  # $-expressions are PowerShell, not shell
ps_parse='$e = $null; $null = [System.Management.Automation.Language.Parser]::ParseFile($env:PS1_FILE, [ref]$null, [ref]$e)
foreach ($x in $e) { "      line $($x.Extent.StartLineNumber): $($x.Message)" }
if ($e) { exit 1 }'
if command -v pwsh >/dev/null; then
  while IFS= read -r -d '' f; do
    if PS1_FILE="$f" pwsh -NoProfile -NonInteractive -Command "$ps_parse"; then pass "$f"; else flunk "$f"; fi
  done < <(find . -type f -name '*.ps1' -not -path './.git/*' -print0)
elif [ -n "${CI:-}" ]; then
  flunk "pwsh not found; CI must parse the *.ps1 installers"
else
  echo "skip  *.ps1 (pwsh not installed; CI checks them)"
fi

echo "== smoke"
# Snapshot with the real HOME so both sides see the same global git config (excludesFile).
real_home="$HOME"
repo_status() { HOME="$real_home" git status --porcelain; }
before=$(repo_status)
sandbox=$(mktemp -d)
trap 'rm -rf "$sandbox"' EXIT
export HOME="$sandbox/home"
proj="$sandbox/proj"
mkdir -p "$HOME" "$proj"

# run LABEL CMD... — run an installer, show its output on failure
run() {
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then pass "$label"; else flunk "$label"; printf '%s\n' "$out" | sed 's/^/      /'; fi
}

run "skills-hive install.sh" \
  bash hives/skills-hive/scripts/install.sh --global --all --harness claude-code --harness cursor
if [ -n "$(find "$HOME/.claude/skills" -name SKILL.md 2>/dev/null)" ]; then
  pass "skills-hive installed SKILL.md files"
else
  flunk "skills-hive installed no SKILL.md files"
fi

run "rules-hive install.sh" bash hives/rules-hive/scripts/install.sh --dir "$proj"
if [ -s "$proj/AGENTS.md" ]; then pass "rules-hive wrote AGENTS.md"; else flunk "rules-hive wrote no AGENTS.md"; fi

run "agents-hive install.py --dry-run" python3 hives/agents-hive/scripts/install.py --dir "$proj" --dry-run
run "mcp-hive install.py --dry-run" python3 hives/mcp-hive/scripts/install.py --dir "$proj" --dry-run
run "plugins-hive install.py --dry-run" \
  python3 hives/plugins-hive/scripts/install.py --dir "$proj" --hives-dir hives --dry-run
run "projects-hive init.py --dry-run" \
  python3 hives/projects-hive/scripts/init.py --name ci-smoke --dir "$sandbox/new" --hives-dir hives --dry-run

# workflows-hive: crash after step 1, then resume must skip it and finish step 2.
runs="$sandbox/runs"
printf 'one two three\nfour five\n' > "$sandbox/words.txt"
wf() { python3 hives/workflows-hive/scripts/run.py --state-dir "$runs" "$@" 2>&1; }
out=$(wf start word-count --input path="$sandbox/words.txt" --crash-after read); code=$?
run_id=$(printf '%s\n' "$out" | sed -n 's/^start \(run_[0-9a-f]*\).*/\1/p')
if [ "$code" -eq 75 ] && [ -n "$run_id" ]; then
  pass "workflows-hive run.py stops after step 1"
else
  flunk "workflows-hive run.py stops after step 1"; printf '%s\n' "$out" | sed 's/^/      /'
fi
out=$(wf resume "$run_id"); code=$?
if [ "$code" -eq 0 ] && printf '%s\n' "$out" | grep -q '^skip  read' \
  && printf '%s\n' "$out" | grep -q '"words": 5' && printf '%s\n' "$out" | grep -q '"tokens"'; then
  pass "workflows-hive run.py resumes at step 2 and reports result and cost"
else
  flunk "workflows-hive run.py resumes at step 2 and reports result and cost"
  printf '%s\n' "$out" | sed 's/^/      /'
fi

if [ "$(repo_status)" != "$before" ]; then
  flunk "installers left changes in the repo"; repo_status | sed 's/^/      /'
fi

[ "$fail" -eq 0 ] && echo "OK  installer checks passed"
exit "$fail"
