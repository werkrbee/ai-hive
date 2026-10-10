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
card_pid=""
trap '[ -n "$card_pid" ] && { kill "$card_pid"; wait "$card_pid"; } 2>/dev/null; rm -rf "$sandbox"' EXIT
export HOME="$sandbox/home"
proj="$sandbox/proj"
mkdir -p "$HOME" "$proj"

# run LABEL CMD... — run an installer, show its output on failure
run() {
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then pass "$label"; else flunk "$label"; printf '%s\n' "$out" | sed 's/^/      /'; fi
}

# Verify complete skill directories and the exact selection, not just any SKILL.md.
check_skills() {
  local label="$1" dest="$2"; shift 2
  local skill expected actual
  expected=$(printf '%s\n' "$@" | sort)
  actual=$(find "$dest" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null | sort)
  if [ "$actual" = "$expected" ]; then pass "$label selection"; else flunk "$label selection"; fi
  for skill in "$@"; do
    if diff -r "hives/skills-hive/skills/$skill" "$dest/$skill" >/dev/null 2>&1; then
      pass "$label $skill contents"
    else
      flunk "$label $skill contents"
    fi
  done
}

# A copied hive keeps the no-argument/project install out of the real checkout.
cp -R hives/skills-hive "$sandbox/skills-hive"
skill_installer="$sandbox/skills-hive/scripts/install.sh"
run "skills-hive default project install" bash "$skill_installer"
check_skills "skills-hive default project" "$sandbox/skills-hive/.cursor/skills" barry discover-outcomes

run "skills-hive default global install" bash "$skill_installer" --global --harness cursor --harness claude-code
for dest in "$HOME/.cursor/skills" "$HOME/.claude/skills"; do
  check_skills "skills-hive default global $dest" "$dest" barry discover-outcomes
done

run "skills-hive explicit Barry install" bash "$skill_installer" --global --harness codex --skill barry
check_skills "skills-hive explicit Barry" "$HOME/.codex/skills" barry discover-outcomes

# Selecting the dependency explicitly, in either order, must not install it twice.
for first in barry discover-outcomes; do
  second=barry
  [ "$first" = barry ] && second=discover-outcomes
  dest_home="$sandbox/explicit-$first"
  out=$(HOME="$dest_home" bash "$skill_installer" --global --harness cursor --skill "$first" --skill "$second" 2>&1); code=$?
  if [ "$code" -eq 0 ] && [ "$(printf '%s\n' "$out" | grep -c '^installed: discover-outcomes ->')" -eq 1 ]; then
    pass "skills-hive explicit dependency after $first installed once"
  else
    flunk "skills-hive explicit dependency after $first installed once"
    printf '%s\n' "$out" | sed 's/^/      /'
  fi
  check_skills "skills-hive explicit dependency after $first" "$dest_home/.cursor/skills" barry discover-outcomes
done

for skill in patricia discover-outcomes; do
  dest_home="$sandbox/only-$skill"
  run "skills-hive $skill only" env HOME="$dest_home" bash "$skill_installer" --global --harness cursor --skill "$skill"
  check_skills "skills-hive $skill only" "$dest_home/.cursor/skills" "$skill"
done

# A damaged source must fail before installing Barry without its dependency.
cp -R hives/skills-hive "$sandbox/missing-dependency"
rm "$sandbox/missing-dependency/skills/discover-outcomes/SKILL.md"
dest_home="$sandbox/missing-home"
out=$(HOME="$dest_home" bash "$sandbox/missing-dependency/scripts/install.sh" --global --harness cursor --skill barry 2>&1); code=$?
if [ "$code" -ne 0 ] && [ ! -e "$dest_home/.cursor/skills/barry" ] \
  && printf '%s\n' "$out" | grep -q '^error: discover-outcomes '; then
  pass "skills-hive missing dependency fails before copying"
else
  flunk "skills-hive missing dependency fails before copying"
  printf '%s\n' "$out" | sed 's/^/      /'
fi

all_home="$sandbox/all-home"
run "skills-hive install.sh" \
  env HOME="$all_home" bash hives/skills-hive/scripts/install.sh --global --all --harness claude-code --harness cursor
for dest in "$all_home/.claude/skills" "$all_home/.cursor/skills"; do
  check_skills "skills-hive all $dest" "$dest" barry discover-outcomes patricia
done

run "rules-hive install.sh" bash hives/rules-hive/scripts/install.sh --dir "$proj"
if [ -s "$proj/AGENTS.md" ]; then pass "rules-hive wrote AGENTS.md"; else flunk "rules-hive wrote no AGENTS.md"; fi

run "agents-hive install.py --dry-run" python3 hives/agents-hive/scripts/install.py --dir "$proj" --dry-run
# Local servers only; remote entries fetch their Server Card, tested offline below.
run "mcp-hive install.py --dry-run" python3 hives/mcp-hive/scripts/install.py --dir "$proj" --dry-run \
  --server filesystem --server git --server fetch

# mcp-hive Server Cards: serve an AI Catalog and a card from localhost, then resolve a
# registry entry through the catalog. The card requires a secret bearer token.
cards="$sandbox/cards"
mkdir -p "$cards/.well-known" "$sandbox/registry/demo"
cat > "$cards/card.json" <<'JSON'
{"$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
 "name": "com.example/demo", "version": "1.0.0", "description": "Fixture card.",
 "remotes": [{"type": "streamable-http", "url": "https://demo.example.com/mcp",
   "headers": [{"name": "Authorization", "isRequired": true, "isSecret": true,
     "value": "Bearer {token}", "variables": {"token": {"isSecret": true}}}]}]}
JSON
python3 - "$cards" "$sandbox/port" <<'PY' &
import functools, http.server, sys
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=sys.argv[1])
handler.func.log_message = lambda *a: None
srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
open(sys.argv[2], "w").write(str(srv.server_port))
srv.serve_forever()
PY
card_pid=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do [ -s "$sandbox/port" ] && break; sleep 0.2; done
port=$(cat "$sandbox/port" 2>/dev/null)
printf '{"specVersion": "1.0", "entries": [{"identifier": "urn:air:localhost:mcp:demo",
  "type": "application/mcp-server-card+json", "url": "http://127.0.0.1:%s/card.json"}]}\n' \
  "$port" > "$cards/.well-known/ai-catalog.json"
printf '{"name": "demo", "description": "Fixture.", "discovery": {"catalog":
  "http://127.0.0.1:%s/.well-known/ai-catalog.json", "identifier": "urn:air:localhost:mcp:demo"}}\n' \
  "$port" > "$sandbox/registry/demo/mcp.json"
out=$(python3 hives/mcp-hive/scripts/install.py --servers-dir "$sandbox/registry" --dir "$proj" \
  --harness claude-code --dry-run 2>&1); code=$?
if [ "$code" -eq 0 ] && printf '%s\n' "$out" | grep -q '"url": "https://demo.example.com/mcp"' \
  && printf '%s\n' "$out" | grep -q 'Bearer ${DEMO_TOKEN}'; then
  pass "mcp-hive install.py resolves a Server Card through an AI Catalog"
else
  flunk "mcp-hive install.py resolves a Server Card through an AI Catalog"
  printf '%s\n' "$out" | sed 's/^/      /'
fi
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
