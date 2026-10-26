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

# agents-hive: entra.sh plans before it asks, against a stubbed az.
run "agents-hive entra.sh plan and refusals (stubbed az)" \
  bash hives/agents-hive/deploy/azure/tests/entra_test.sh

# agents-hive: deploy.sh checks role ids before its first what-if, against a stubbed az.
run "agents-hive deploy.sh role id check (stubbed az)" \
  bash hives/agents-hive/deploy/azure/tests/deploy_test.sh

# agents-hive: prices.sh reads the Retail Prices API's pages, against a stubbed curl.
run "agents-hive prices.sh lookup (stubbed curl)" \
  bash hives/agents-hive/deploy/azure/tests/prices_test.sh

# workflows-hive: crash after step 1, then resume must skip it and finish step 2.
runs="$sandbox/runs"
printf 'one two three\nfour five\n' > "$sandbox/words.txt"
wf() { python3 hives/workflows-hive/scripts/run.py --state-dir "$runs" "$@" 2>&1; }
# A person answers at a terminal, so answers run with a pseudo-terminal as stdin and stdout.
at_terminal() {
  python3 -c 'import os, pty, subprocess, sys
main, sub = pty.openpty()
p = subprocess.Popen(sys.argv[1:], stdin=sub, stdout=sub, stderr=sub)
os.close(sub)
out = b""
while True:
    try:
        chunk = os.read(main, 4096)
    except OSError:
        break
    if not chunk:
        break
    out += chunk
sys.stdout.write(out.decode(errors="replace").replace("\r\n", "\n"))
sys.exit(p.wait())' "$@"
}
wft() { at_terminal python3 hives/workflows-hive/scripts/run.py --state-dir "$runs" "$@" 2>&1; }
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

# workflows-hive: a step marked approval pauses the run, a restart keeps it paused, and
# only approve runs the step; deny fails the run without running it.
check_wf() {  # $1 = label, $2 = 1 if it holds; prints $out on failure
  if [ "$2" -eq 1 ]; then pass "$1"; else flunk "$1"; printf '%s\n' "$out" | sed 's/^/      /'; fi
}
holds() { if "$@" >/dev/null 2>&1; then echo 1; else echo 0; fi; }
out=$(wf start approved-word-count --input path="$sandbox/words.txt"); code=$?
run_id=$(printf '%s\n' "$out" | sed -n 's/^start \(run_[0-9a-f]*\).*/\1/p')
check_wf "workflows-hive run.py pauses before an approval step" "$(holds eval \
  '[ "$code" -eq 2 ] && printf "%s\n" "$out" | grep -q "\"status\": \"input_required\"" \
   && ! printf "%s\n" "$out" | grep -q "^run   count"')"
out=$(wf resume "$run_id"); code=$?
check_wf "workflows-hive run.py stays paused after a restart" "$(holds eval \
  '[ "$code" -eq 2 ] && ! printf "%s\n" "$out" | grep -q "^run   count"')"
out=$(wft approve "$run_id" --by ci); code=$?
check_wf "workflows-hive run.py runs the step once approved" "$(holds eval \
  '[ "$code" -eq 0 ] && printf "%s\n" "$out" | grep -q "^run   count" \
   && printf "%s\n" "$out" | grep -q "\"words\": 5" && grep -q "\"by\": \"ci\"" "$runs/$run_id.json"')"
out=$(wf start approved-word-count --input path="$sandbox/words.txt")
run_id=$(printf '%s\n' "$out" | sed -n 's/^start \(run_[0-9a-f]*\).*/\1/p')
out=$(wft deny "$run_id" --reason "not now" --by ci); code=$?
check_wf "workflows-hive run.py fails the run on deny, without running the step" "$(holds eval \
  '[ "$code" -eq 1 ] && printf "%s\n" "$out" | grep -q "approval denied by ci: not now" \
   && ! printf "%s\n" "$out" | grep -q "^run   count"')"

# workflows-hive: a step within its budget finishes; one past its seconds is stopped, one
# over its tokens fails the run with its cost still counted, and a budget above the
# worker's contract is refused before the run starts.
plans="$sandbox/plans"
mkdir -p "$plans/slow" "$plans/costly" "$plans/big" "$sandbox/contracts/count-words"
printf '%s\n' '{"name": "slow", "version": 1, "inputs": {"type": "object"}, "output": null,
  "steps": [{"id": "nap", "worker": "wait", "input": {"seconds": 10}, "budget": {"seconds": 1}}]}' \
  > "$plans/slow/workflow.json"
printf '%s\n' '{"name": "costly", "version": 1, "inputs": {"type": "object"}, "output": null,
  "steps": [{"id": "read", "worker": "read-text", "input": {"path": "${inputs.path}"},
    "budget": {"tokens": 2}}]}' > "$plans/costly/workflow.json"
printf '%s\n' '{"name": "big", "version": 1, "inputs": {"type": "object"}, "output": null,
  "steps": [{"id": "count", "worker": "count-words", "input": {"text": "a b"},
    "budget": {"tokens": 5000}}]}' > "$plans/big/workflow.json"
printf '%s\n' '{"budget": {"tokens": 1000}}' > "$sandbox/contracts/count-words/contract.json"
wfp() { wf --workflows-dir "$plans" --contracts-dir "$sandbox/contracts" "$@"; }
out=$(wf start budgeted-word-count --input path="$sandbox/words.txt"); code=$?
check_wf "workflows-hive run.py finishes steps within their budgets" "$(holds eval \
  '[ "$code" -eq 0 ] && printf "%s\n" "$out" | grep -q "\"words\": 5"')"
began=$SECONDS
out=$(wfp start slow); code=$?
check_wf "workflows-hive run.py stops a step past its seconds" "$(holds eval \
  '[ "$code" -eq 1 ] && [ $((SECONDS - began)) -lt 8 ] \
   && printf "%s\n" "$out" | grep -q "ran past its budget of 1 second\""')"
out=$(wfp start costly --input path="$sandbox/words.txt"); code=$?
check_wf "workflows-hive run.py fails a step over its tokens, still counting its cost" "$(holds eval \
  '[ "$code" -eq 1 ] && printf "%s\n" "$out" | grep -q "spent 6 tokens, over its budget of 2" \
   && printf "%s\n" "$out" | grep -q "\"tokens\": 6"')"
n=$(find "$runs" -name 'run_*.json' | wc -l)
out=$(wfp start big); code=$?
check_wf "workflows-hive run.py refuses a budget above its worker's contract" "$(holds eval \
  '[ "$code" -eq 1 ] && printf "%s\n" "$out" | grep -q "above the .count-words. contract" \
   && [ "$(find "$runs" -name "run_*.json" | wc -l)" -eq "$n" ]')"

# workflows-hive: a step's actions are decided by the approval policy. Under the Charter,
# a read runs and a push pauses, approval: false can't skip that pause and approval: true
# still forces one. Under lineup-etiquette, a bullpen call runs, a blast pauses showing
# its present items, and a message to someone who didn't opt in fails the run without
# running the step. An action no mandate allows is denied, and one outside the policy's
# vocabulary is refused before the run starts.
acts() {  # $1 = plan name, $2 = extra step fields, e.g. "actions": [...]
  mkdir -p "$plans/$1"
  printf '{"name": "%s", "version": 1, "inputs": {"type": "object"}, "output": null,
  "steps": [{"id": "count", "worker": "count-words", "input": {"text": "a b"}, %s}]}\n' \
    "$1" "$2" > "$plans/$1/workflow.json"
}
acts read '"actions": [{"action": "fs.read"}]'
acts write '"actions": [{"action": "fs.write"}]'
acts push '"actions": [{"action": "vcs.push"}]'
acts push-unflagged '"approval": false, "actions": [{"action": "vcs.push"}]'
acts read-flagged '"approval": true, "actions": [{"action": "fs.read"}]'
acts bullpen '"actions": [{"action": "message.send", "scope": {"channel": "sms", "audience": "bullpen"},
  "trigger": "bullpen.slot-opened", "facts": {"recipient.notifyOptIn": true}}]'
acts blast '"actions": [{"action": "message.send", "scope": {"channel": "sms", "audience": "group"},
  "facts": {"recipient.notifyOptIn": true}}]'
acts opted-out '"actions": [{"action": "message.send", "scope": {"channel": "sms", "audience": "group"},
  "facts": {"recipient.notifyOptIn": false}}]'
acts cancel '"actions": [{"action": "lineup.event.cancel", "facts": {"actor.role": "organizer"}}]'
lineup=hives/rules-hive/examples/lineup-etiquette/policy.json
read_only=hives/workflows-hive/tests/read-only-policy/policy.json
outcome() {  # $1 = label, $2 = expected exit, $3 = text the output must have; then start args
  local label="$1" want="$2" text="$3"; shift 3
  out=$(wfp start "$@"); code=$?
  check_wf "$label" "$(holds eval '[ "$code" -eq "$want" ] && printf "%s\n" "$out" | grep -qF -- "$text"')"
}
outcome "workflows-hive run.py runs a step the Charter allows" 0 '"status": "completed"' read
outcome "workflows-hive run.py pauses a step the Charter gates" 2 'needs approval under approve.vcs.push' push
run_id=$(printf '%s\n' "$out" | sed -n 's/^start \(run_[0-9a-f]*\).*/\1/p')
out=$(at_terminal python3 hives/workflows-hive/scripts/run.py --state-dir "$runs" \
  --workflows-dir "$plans" --contracts-dir "$sandbox/contracts" approve "$run_id" --by ci 2>&1); code=$?
check_wf "workflows-hive run.py runs a gated step once approved" "$(holds eval \
  '[ "$code" -eq 0 ] && printf "%s\n" "$out" | grep -q "^run   count"')"
outcome "workflows-hive run.py can't skip a gated step with approval: false" 2 \
  'needs approval under approve.vcs.push' push-unflagged
outcome "workflows-hive run.py still pauses on approval: true" 2 '"status": "input_required"' read-flagged
outcome "workflows-hive run.py runs a lineup bullpen call" 0 '"status": "completed"' bullpen --policy "$lineup"
outcome "workflows-hive run.py pauses a lineup blast, showing its present items" 2 \
  'under organizer.blast, showing message, recipient count, estimated cost' blast --policy "$lineup"
outcome "workflows-hive run.py fails a prohibited message without running the step" 1 \
  'message.send is prohibited by messages.opt-in-only' opted-out --policy "$lineup"
check_wf "workflows-hive run.py never ran the prohibited step" "$(holds eval \
  '! printf "%s\n" "$out" | grep -q "^run   count"')"
outcome "workflows-hive run.py denies an action no mandate allows" 1 \
  'fs.write is denied: no mandate' write --policy "$read_only"
outcome "workflows-hive run.py refuses an action outside the policy's vocabulary" 1 \
  "action 'lineup.event.cancel' isn't in" cancel

# workflows-hive: cancel ends a paused run at once, and the step never runs.
out=$(wf start approved-word-count --input path="$sandbox/words.txt")
run_id=$(printf '%s\n' "$out" | sed -n 's/^start \(run_[0-9a-f]*\).*/\1/p')
out=$(wf cancel "$run_id" --by ci); code=$?
check_wf "workflows-hive run.py cancels a paused run" "$(holds eval \
  '[ "$code" -eq 1 ] && printf "%s\n" "$out" | grep -q "\"status\": \"cancelled\"" \
   && printf "%s\n" "$out" | grep -q "cancelled by ci"')"
out=$(wft approve "$run_id" --by ci); code=$?
check_wf "workflows-hive run.py can't approve a cancelled run" "$(holds eval \
  '[ "$code" -eq 1 ] && ! printf "%s\n" "$out" | grep -q "^run   count"')"

# workflows-hive: a passport's never actions are prohibited before any mandate, an answer
# needs an actor ID, and every run above left a whole audit log that ends where each run
# record says it does.
outcome "workflows-hive run.py prohibits what a passport puts under never" 1 \
  'fs.write is prohibited by passport.patricia.never.fs.write' write --passport patricia
out=$(wf start approved-word-count --input path="$sandbox/words.txt")
run_id=$(printf '%s\n' "$out" | sed -n 's/^start \(run_[0-9a-f]*\).*/\1/p')
out=$(WORKFLOWS_HIVE_ACTOR= wft approve "$run_id"); code=$?
check_wf "workflows-hive run.py refuses an answer without an actor ID" "$(holds eval \
  '[ "$code" -eq 1 ] && printf "%s\n" "$out" | grep -q "needs an actor ID"')"

# workflows-hive: every pause is an item in the review queue. The queue lists it, refuses
# an answer without a terminal or with the wrong approval ID, and runs the step once a
# person approves it at a terminal. A pause unanswered for seven days expires and fails
# its run.
rq() { python3 hives/workflows-hive/scripts/review_queue.py --state-dir "$runs" "$@" 2>&1; }
out=$(wf start approved-word-count --input path="$sandbox/words.txt")
run_id=$(printf '%s\n' "$out" | sed -n 's/^start \(run_[0-9a-f]*\).*/\1/p')
item=$(sed -n 's/.*review_queue.py show \(sha256:[0-9a-f]*\).*/\1/p' <<<"$out")
out=$(rq list); code=$?
check_wf "workflows-hive review_queue.py lists a paused run's approval" "$(holds eval \
  '[ "$code" -eq 0 ] && [ -n "$item" ] && printf "%s\n" "$out" | grep -q "^${item:7:12}  approval    open .*$run_id"')"
out=$(rq approve "$item" --by ci < /dev/null); code=$?
check_wf "workflows-hive review_queue.py refuses to answer without a terminal" "$(holds eval \
  '[ "$code" -eq 1 ] && printf "%s\n" "$out" | grep -q "without an interactive terminal"')"
out=$(wft approve "$run_id" --by ci --id "sha256:$(printf '0%.0s' {1..64})"); code=$?
check_wf "workflows-hive run.py refuses an answer with the wrong approval ID" "$(holds eval \
  '[ "$code" -eq 1 ] && printf "%s\n" "$out" | grep -q "an answer answers only what was shown" \
   && ! printf "%s\n" "$out" | grep -q "^run   count"')"
out=$(at_terminal python3 hives/workflows-hive/scripts/review_queue.py --state-dir "$runs" \
  approve "${item:7:12}" --by ci 2>&1); code=$?
check_wf "workflows-hive review_queue.py approves at a terminal, and the step runs" "$(holds eval \
  '[ "$code" -eq 0 ] && printf "%s\n" "$out" | grep -q "^run   count" \
   && rq list --all | grep -q "^${item:7:12}  approval    answered"')"
out=$(wf start approved-word-count --input path="$sandbox/words.txt")
run_id=$(printf '%s\n' "$out" | sed -n 's/^start \(run_[0-9a-f]*\).*/\1/p')
python3 - "$runs/$run_id.json" <<'PY'
import json, sys
path = sys.argv[1]
run = json.load(open(path))
run["pending"]["expiresAt"] = "2000-01-01T00:00:00Z"  # as if seven days had passed
json.dump(run, open(path, "w"))
PY
out=$(rq list); code=$?
check_wf "workflows-hive review_queue.py expires a pause past seven days, failing its run" "$(holds eval \
  '[ "$code" -eq 0 ] && printf "%s\n" "$out" | grep -q "^expire $run_id" \
   && ! printf "%s\n" "$out" | grep -q "open .*$run_id" \
   && grep -q "expired unanswered" "$runs/$run_id.json" && rq list --all | grep -q "expired"')"

out=$(python3 hives/knowledge-hive/scripts/check_audit.py "$sandbox/audit.jsonl" --runs "$runs" 2>&1); code=$?
check_wf "workflows-hive run.py leaves a whole audit log" "$(holds eval '[ "$code" -eq 0 ]')"

# workflows-hive: the engine as a library, with open runs that grow, model turns, crashes
# mid-turn and mid-step, and cancel.
# -B: no __pycache__ left in the repo.
run "workflows-hive engine library tests" python3 -B -m unittest discover -s hives/workflows-hive/tests
# agents-hive: passports only narrow their contracts, pins match, and cards link them.
run "agents-hive passport tests" python3 -B -m unittest discover -s hives/agents-hive/tests
# knowledge-hive: the audit log's hash rules, and the verifier's reports and anchors.
run "knowledge-hive audit log tests" python3 -B -m unittest discover -s hives/knowledge-hive/tests

if [ "$(repo_status)" != "$before" ]; then
  flunk "installers left changes in the repo"; repo_status | sed 's/^/      /'
fi

[ "$fail" -eq 0 ] && echo "OK  installer checks passed"
exit "$fail"
