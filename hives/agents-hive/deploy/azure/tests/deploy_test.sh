#!/usr/bin/env bash
# Exercise deploy.sh's checks against a stubbed az. A passport the promotion check refuses
# stops before any az call. Role ids: the current ids pass and
# reach the first what-if; a wrong id, or a lookup that fails, stops before any what-if or
# change. Models: generally available ones pass, from any publisher, each named with the
# API the server would use and the chosen one marked; one that is preview, missing from
# the catalog, offered only for another account kind, without chat completions or not
# offered with its sku stops before the what-if, as does a modelDeployment that names no
# model, and so does one that isn't the model Patricia's passport pins. A what-if that
# fails stops without asking to apply anything. Each case runs deploy.sh from a throwaway
# git checkout, since it deploys only a clean one.
#
# Hosted evaluations: once a template with the weekly job is deployed, its results and
# queue are downloaded from the share, with the account key in the environment and never
# an argument, and drift there stops the deploy before any change, as does a download that
# fails. So does a job that has gone quiet: one whose newest evaluation, or whose creation
# when it has none, is more than eight days old, or one that can't be looked up; a job
# that recorded recently, or was created within the week, goes on. Retention: the audit log's policy is set after the infrastructure, as its own
# gated step, and locked only with --lock-audit-retention and the account's name typed; a
# locked policy is left alone.
#
# Rollback: from a checkout whose passport went from v1 to v2, --rollback 1 deploys v1's
# commit, through every gated step, with v1's promotion check, and records who did it in
# the audit log and why in a record beside it. Stopped before the app, it records nothing;
# deployed but unable to write the audit log, it fails, naming the command that records
# it. A modelDeployment that isn't the model v1 pins, a pinned model the catalog no longer
# has, a version that isn't earlier, a missing reason and a passport from before trust
# evaluation each stop it before any change. Bash 3.2 safe; run it with /bin/bash on
# macOS.
#
# Usage: tests/deploy_test.sh           (from hives/agents-hive/deploy/azure, or anywhere)
set -u

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0

# The stub. $STUB/roles holds the subscription's role definitions ("id name"),
# $STUB/params.json what build-params prints and $STUB/catalog.json the region's model
# catalog; every call is appended to $STUB/calls. $STUB/deployed is whether a deployment
# named main exists (0 or 1), $STUB/outputs its outputs, $STUB/hosted/ what the share's
# assurance/ holds, $STUB/job-created when the weekly job was created (none: no job) and
# $STUB/policy the audit container's retention policy, as container-rm show prints it. STUB_FAIL, when set, is a pattern; a call whose arguments
# match it fails.
mkdir -p "$work/bin"
cat > "$work/bin/az" <<'STUB'
#!/usr/bin/env bash
args="$*"
echo "$args" >> "$STUB/calls"
if [ -n "${STUB_FAIL:-}" ] && printf '%s' "$args" | grep -q -- "$STUB_FAIL"; then
  echo "stub: failing: $args" >&2; exit 1
fi
case "$args" in
  "role definition list"*)
    id=$(printf '%s' "$args" | sed -n 's/.*--name \([^ ]*\).*/\1/p')
    awk -v i="$id" '$1==i{$1=""; sub(/^ /, ""); print}' "$STUB/roles" ;;
  "group exists"*) echo true ;;
  "group show"*) echo eastus2 ;;
  "bicep build-params"*) cat "$STUB/params.json" ;;
  "cognitiveservices model list"*) cat "$STUB/catalog.json" ;;
  "deployment group list"*) cat "$STUB/deployed" 2>/dev/null || echo 0 ;;
  "deployment group show"*) cat "$STUB/outputs" ;;
  "storage account keys list"*) echo "s3cretkey" ;;
  "storage file download-batch"*)
    echo "${AZURE_STORAGE_KEY:-}" > "$STUB/key"
    dest=$(printf '%s' "$args" | sed -n 's/.*--destination \([^ ]*\).*/\1/p')
    if [ -d "$STUB/hosted" ]; then mkdir -p "$dest/assurance" && cp -R "$STUB/hosted/." "$dest/assurance/"; fi ;;
  "containerapp job list"*) cat "$STUB/job-created" 2>/dev/null || true ;;
  "storage container-rm show"*) cat "$STUB/policy" 2>/dev/null || printf 'False\n' ;;
  "storage container immutability-policy create"*) printf 'True\tUnlocked\t365\tTrue\n' > "$STUB/policy" ;;
  "storage container immutability-policy show"*) echo '"etag-1"' ;;
  "storage container immutability-policy lock"*) printf 'True\tLocked\t365\tTrue\n' > "$STUB/policy" ;;
  "deployment group what-if"*) echo "what-if shown" ;;
  "deployment group create"*) echo '{"registry": {"value": "reg.azurecr.io"}, "agentCard": {"value": "https://card"},
    "auditAccount": {"value": "patricialogtest"}, "auditContainer": {"value": "audit"}}' ;;
  "acr build"*) echo "built" ;;
esac
STUB
chmod +x "$work/bin/az"

# The region's catalog: GA models from three publishers (Anthropic's for the Messages
# API), a preview one, a GA one that only does the Responses API, a GA one offered only as
# Standard, one offered only for the OpenAI account kind and one whose skus differ by
# kind. Some appear more than once, as the real catalog lists a model once per account
# kind.
cat > "$work/catalog.json" <<'JSON'
[
 {"kind": "OpenAI", "model": {"format": "OpenAI", "name": "gpt-5.4", "version": "2026-03-05", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "GlobalStandard"}]}},
 {"kind": "AIServices", "model": {"format": "OpenAI", "name": "gpt-5.4", "version": "2026-03-05", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "GlobalStandard"}]}},
 {"kind": "AIServices", "model": {"format": "DeepSeek", "name": "DeepSeek-V3.2", "version": "1", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "GlobalStandard"}]}},
 {"kind": "AIServices", "model": {"format": "xAI", "name": "grok-next", "version": "1", "lifecycleStatus": "Preview", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "GlobalStandard"}]}},
 {"kind": "AIServices", "model": {"format": "OpenAI", "name": "gpt-codex", "version": "1", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"responses": "true", "chatCompletion": "false"}, "skus": [{"name": "GlobalStandard"}]}},
 {"kind": "AIServices", "model": {"format": "Mistral AI", "name": "mistral-x", "version": "1", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "Standard"}]}},
 {"kind": "OpenAI", "model": {"format": "OpenAI", "name": "gpt-legacy", "version": "1", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "GlobalStandard"}]}},
 {"kind": "OpenAI", "model": {"format": "OpenAI", "name": "gpt-split", "version": "1", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "GlobalStandard"}]}},
 {"kind": "AIServices", "model": {"format": "OpenAI", "name": "gpt-split", "version": "1", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "Standard"}]}},
 {"kind": "AIServices", "model": {"format": "Anthropic", "name": "claude-x", "version": "1", "lifecycleStatus": "GenerallyAvailable", "capabilities": {"chatCompletion": "true"}, "skus": [{"name": "GlobalStandard"}]}}
]
JSON
gpt='{"deployment": "review-b", "format": "OpenAI", "name": "gpt-5.4", "version": "2026-03-05", "sku": "GlobalStandard"}'
deepseek='{"deployment": "review-c", "format": "DeepSeek", "name": "DeepSeek-V3.2", "version": "1", "sku": "GlobalStandard"}'

# run CASE BICEP — deploy.sh from a clean checkout holding BICEP as main.bicep, with
# $MODELS (a JSON array, default GPT-5.4 and DeepSeek) as the models parameter and
# $CHOSEN (default the first model's deployment) as modelDeployment, answering $ANSWER
# (default no) at every prompt, or $ANSWERS in turn, with deploy_args before the
# positional ones. Patricia's passport pins $PINNED_NOW (default GPT-5.4). With $HISTORY
# set, it is v1, pinning $PINNED (default claude-x 1), in one commit and v2, pinning
# GPT-5.4, in the next, whose promotion check says so; $NO_EVAL_AT_V1 leaves trust_eval.py
# out of v1. The promotion check refuses when $PROMOTION is "refused", and, given the
# hosted results, when $HOSTED is "drift".
deploy_args=()
run() {
  export STUB="$work/$1"
  local repo="$STUB/repo" dir="$STUB/repo/hives/agents-hive/deploy/azure"
  mkdir -p "$dir"
  printf '%s\n' "7f951dda-4ed3-4680-a7ca-43fe172d538d AcrPull" \
    "a97b65f3-24c7-4388-baec-2e87135dc908 Cognitive Services User" \
    "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd Cognitive Services OpenAI User" \
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe Storage Blob Data Contributor" \
    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1 Storage Blob Data Reader" > "$STUB/roles"
  : > "$STUB/calls"
  cp "$work/catalog.json" "$STUB/catalog.json"
  python3 -c 'import json, sys; models = json.loads(sys.argv[1]); print(json.dumps({"parametersJson": json.dumps(
    {"parameters": {"models": {"value": models}, "modelDeployment": {"value": sys.argv[2] or models[0]["deployment"]}}})}))' \
    "${MODELS:-[$gpt, $deepseek]}" "${CHOSEN:-}" > "$STUB/params.json"
  cp "$here/../deploy.sh" "$dir/"
  cp "$2" "$dir/main.bicep"
  # The promotion check, stubbed: it passes unless $PROMOTION is "refused", or $HOSTED is
  # "drift" and it was given hosted results that exist.
  mkdir -p "$repo/hives/agents-hive/scripts"
  cat > "$repo/hives/agents-hive/scripts/trust_eval.py" <<'PY'
import os, sys
if os.environ.get("PROMOTION") == "refused":
    sys.exit("refused: passport patricia v4's baseline was recorded against other pins")
if "--results" in sys.argv:
    results = sys.argv[sys.argv.index("--results") + 1]
    if os.environ.get("HOSTED") == "drift" and os.path.isfile(results):
        sys.exit("refused: drift sha256:abc holds promotion until a person answers it")
    print(f"hosted: read {os.path.basename(results)}")
print(f"{sys.argv[2]}: baseline recorded against its pins, and no drift holds it")
PY
  git -C "$repo" init -q
  mkdir -p "$repo/hives/agents-hive/passports/patricia"
  set -- ${PINNED_NOW:-gpt-5.4 2026-03-05}
  passport "$repo" 1 "$1" "$2"
  if [ -n "${HISTORY:-}" ]; then
    for script in hives/agents-hive/scripts/rollback.py hives/knowledge-hive/scripts/check_audit.py; do
      mkdir -p "$repo/$(dirname "$script")"
      cp "$here/../../../../../$script" "$repo/$script"
    done
    mkdir -p "$repo/hives/agents-hive/passports/patricia"
    set -- ${PINNED:-claude-x 1}
    passport "$repo" 1 "$1" "$2"
    [ -z "${NO_EVAL_AT_V1:-}" ] || git -C "$repo" rm -q --cached hives/agents-hive/scripts/trust_eval.py
    git -C "$repo" -c user.name=test -c user.email=test@example.com commit -q -m v1
    echo 'print("checked by v2'"'"'s promotion check")' >> "$repo/hives/agents-hive/scripts/trust_eval.py"
    passport "$repo" 2 gpt-5.4 2026-03-05
  fi
  git -C "$repo" add -A
  git -C "$repo" -c user.name=test -c user.email=test@example.com commit -q -m test
  local a=${ANSWER:-no}
  local answers=${ANSWERS:-"$a $a $a $a $a $a"}
  # One answer per word.
  # shellcheck disable=SC2086
  out=$(printf '%s\n' $answers |
    PATH="$work/bin:$PATH" /bin/bash "$dir/deploy.sh" ${deploy_args[@]+"${deploy_args[@]}"} \
    rg-test eastus2 p.bicepparam 2>&1)
  code=$?
}
passport() {  # REPO VERSION MODEL MODEL-VERSION — write Patricia's passport and stage it all
  printf '{"passport": "patricia", "version": %s, "pins": {"model": {"publisher": "test", "name": "%s", "version": "%s"}}}\n' \
    "$2" "$3" "$4" > "$1/hives/agents-hive/passports/patricia/passport.json"
  git -C "$1" add -A
}
check() {  # LABEL CONDITION...
  local label="$1"; shift
  if "$@"; then echo "pass  $label"; else echo "FAIL  $label"; printf '%s\n' "$out" | sed 's/^/      /'; fail=1; fi
}
has() { printf '%s\n' "$out" | grep -q -- "$1"; }
# Before the role ids, deploy.sh only looks for hosted evaluations: whether the group
# exists and whether anything is deployed in it.
HOSTED_LOOKUPS="group exists|deployment group list"
# Nothing but lookups ran: no what-if, no resource group, no deployment.
only_lookups() { ! grep -qvE "^(role definition list|$HOSTED_LOOKUPS)" "$STUB/calls"; }
# Nothing ran past the hosted lookups: not even a role id was looked up.
no_role_lookups() { ! grep -qvE "^($HOSTED_LOOKUPS)" "$STUB/calls"; }

bicep="$here/../main.bicep"

# A passport that can't be promoted stops everything, before any az call.
PROMOTION=refused run promotion "$bicep"
check "passport not promotable: refused before any az call" \
  eval '[ "$code" -ne 0 ] && has "baseline was recorded against other pins" \
   && has "Patricia.s passport can.t be promoted" && [ ! -s "$STUB/calls" ]'

# The current ids exist, so the check passes and deploy.sh goes on to the first what-if.
run ok "$bicep"
check "current ids: each found by name" \
  eval 'has "acrPull: 7f951dda-4ed3-4680-a7ca-43fe172d538d (AcrPull)" \
   && has "cognitiveServicesUser: a97b65f3-24c7-4388-baec-2e87135dc908 (Cognitive Services User)" \
   && has "cognitiveServicesOpenAiUser: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd (Cognitive Services OpenAI User)"'
check "current ids: goes on to the first what-if" \
  eval 'has "== 1/4 infrastructure" && grep -q "^deployment group what-if" "$STUB/calls"'
check "a promotable passport: checked first, for Patricia" \
  eval 'has "patricia: baseline recorded against its pins"'

# The id the first deploy had wrong: refused, naming it, before anything else.
sed 's/7f951dda-4ed3-4680-a7ca-43fe172d538d/7f951dde-4ef9-41c1-b0ac-8f2d6ec5c76b/' "$bicep" > "$work/wrong.bicep"
run wrong "$work/wrong.bicep"
check "wrong id: refused before any what-if, naming the id" \
  eval '[ "$code" -ne 0 ] && has "role definition 7f951dde-4ef9-41c1-b0ac-8f2d6ec5c76b (acrPull) doesn.t exist" \
   && ! has "== 1/4" && only_lookups'

# A lookup that fails is a refusal too, not a pass.
STUB_FAIL="role definition list" run lookup "$bicep"
check "failed lookup: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "couldn.t look up role definition" && ! has "== 1/4" && only_lookups'

# A main.bicep the check can't read is refused rather than passed unchecked.
sed '/^var acrPull = /d' "$bicep" > "$work/unnamed.bicep"
run unnamed "$work/unnamed.bicep"
check "role var not found: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "can.t find the role id acrPull names" && no_role_lookups'

sed 's/subscriptionResourceId(.Microsoft.Authorization\/roleDefinitions., \([A-Za-z]*\))/\1/' \
  "$bicep" > "$work/none.bicep"
run none "$work/none.bicep"
check "no readable role assignments: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "found no role assignments" && no_role_lookups'

# An assignment written another way is refused, not skipped.
awk '!done && /roleDefinitionId: subscriptionResourceId/ {sub(/subscriptionResourceId\([^)]*\)/, "acrPull"); done=1} {print}' \
  "$bicep" > "$work/other.bicep"
run other "$work/other.bicep"
check "an assignment it can't read: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "assigns 5 roles, but only" && no_role_lookups'

# Models: the catalog is the source of truth.
read_only() { ! grep -qvE "^(role definition list|group (exists|show)|deployment group list|bicep build-params|cognitiveservices model list)" "$STUB/calls"; }

run ga "$bicep"
check "GA models: each passes, from any publisher, and deploy.sh goes on" \
  eval 'has "review-b: OpenAI gpt-5.4 2026-03-05: GenerallyAvailable, GlobalStandard" \
   && has "review-c: DeepSeek DeepSeek-V3.2 1: GenerallyAvailable, GlobalStandard" && has "== 1/4"'
check "GA models: each names its API, and the chosen one is marked" \
  eval 'has "review-b: OpenAI gpt-5.4 2026-03-05: GenerallyAvailable, GlobalStandard, via Chat Completions (modelDeployment: the server calls this one)" \
   && has "review-c: DeepSeek DeepSeek-V3.2 1: GenerallyAvailable, GlobalStandard, via Chat Completions$"'
check "GA models: the catalog read is for the resource group's region" \
  grep -q "^cognitiveservices model list --location eastus2" "$STUB/calls"

MODELS="[$gpt, {\"deployment\": \"review-x\", \"format\": \"xAI\", \"name\": \"grok-next\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run preview "$bicep"
check "preview model: refused before any what-if, with its lifecycle status" \
  eval '[ "$code" -ne 0 ] && has "review-x: xAI grok-next 1 is Preview in eastus2; only GenerallyAvailable models deploy" \
   && ! has "== 1/4" && read_only'

MODELS="[{\"deployment\": \"review-z\", \"format\": \"Meta\", \"name\": \"llama-none\", \"version\": \"9\", \"sku\": \"GlobalStandard\"}]" \
  run missing "$bicep"
check "model not in the catalog: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "review-z: Meta llama-none 9 isn.t in the Foundry model catalog for eastus2" \
   && ! has "== 1/4" && read_only'

MODELS="[{\"deployment\": \"review-m\", \"format\": \"Mistral AI\", \"name\": \"mistral-x\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run sku "$bicep"
check "sku not offered: refused before any what-if, naming what is" \
  eval '[ "$code" -ne 0 ] && has "isn.t offered as GlobalStandard in eastus2 (offered: Standard)" \
   && ! has "== 1/4" && read_only'

MODELS="[{\"deployment\": \"review-r\", \"format\": \"OpenAI\", \"name\": \"gpt-codex\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run responses "$bicep"
check "model without chat completions: refused before any what-if, naming what it does" \
  eval '[ "$code" -ne 0 ] && has "review-r: OpenAI gpt-codex 1 doesn.t do chat completions, so the server can.t call it (it does: responses)" \
   && ! has "== 1/4" && read_only'

MODELS="[{\"deployment\": \"review-o\", \"format\": \"OpenAI\", \"name\": \"gpt-legacy\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run kind "$bicep"
check "model offered only for another account kind: refused before any what-if, naming it" \
  eval '[ "$code" -ne 0 ] && has "review-o: OpenAI gpt-legacy 1 is offered in eastus2 only for OpenAI accounts, not AIServices" \
   && ! has "== 1/4" && read_only'

MODELS="[{\"deployment\": \"review-s\", \"format\": \"OpenAI\", \"name\": \"gpt-split\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run splitkind "$bicep"
check "sku offered only under another account kind: refused, naming what AIServices offers" \
  eval '[ "$code" -ne 0 ] && has "review-s: OpenAI gpt-split 1 isn.t offered as GlobalStandard in eastus2 (offered: Standard)" \
   && ! has "== 1/4" && read_only'

awk "/^resource ai 'Microsoft.CognitiveServices/{f=1} f && /^}/{f=0} !(f && /^  kind: /)" "$bicep" > "$work/nokind.bicep"
run nokind "$work/nokind.bicep"
check "account kind not found in main.bicep: refused before reading the catalog" \
  eval '[ "$code" -ne 0 ] && has "can.t find the Foundry account.s kind" && ! grep -q "^cognitiveservices" "$STUB/calls"'

MODELS="[$gpt, {\"deployment\": \"review-a\", \"format\": \"Anthropic\", \"name\": \"claude-x\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
CHOSEN=review-a PINNED_NOW="claude-x 1" run messages "$bicep"
check "an Anthropic model is shown via Messages, by main.bicep's messagesFormats" \
  eval 'has "review-a: Anthropic claude-x 1: GenerallyAvailable, GlobalStandard, via Messages (modelDeployment: the server calls this one)" \
   && has "review-b: OpenAI gpt-5.4 2026-03-05: GenerallyAvailable, GlobalStandard, via Chat Completions$"'

sed '/^var messagesFormats = /d' "$bicep" > "$work/norule.bicep"
run norule "$work/norule.bicep"
check "messagesFormats not found in main.bicep: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "can.t find messagesFormats in main.bicep" && ! has "== 1/4"'

sed "s/^var messagesFormats = \[/var  messagesFormats=[/" "$bicep" > "$work/spaced.bicep"
MODELS="[$gpt, {\"deployment\": \"review-a\", \"format\": \"Anthropic\", \"name\": \"claude-x\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run spaced "$work/spaced.bicep"
check "messagesFormats spaced differently: still read" \
  eval 'grep -q "^var  messagesFormats=\[" "$STUB/repo/hives/agents-hive/deploy/azure/main.bicep" \
   && has "review-a: Anthropic claude-x 1: GenerallyAvailable, GlobalStandard, via Messages$"'

CHOSEN=review-z run nochosen "$bicep"
check "modelDeployment names no model: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "modelDeployment .review-z. isn.t the deployment of any entry in models" \
   && ! has "== 1/4" && read_only'

STUB_FAIL="cognitiveservices model list" run nocatalog "$bicep"
check "catalog unreadable: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "couldn.t read the Foundry model catalog for eastus2" && ! has "== 1/4" && read_only'

# A what-if that fails shows no plan, so nothing is applied even when the answer is yes.
STUB_FAIL="deployment group what-if" ANSWER=yes run whatiffails "$bicep"
check "what-if fails: stops without asking, and nothing is applied" \
  eval '[ "$code" -ne 0 ] && has "the what-if failed, so there.s no plan to approve" \
   && ! grep -q "^deployment group create" "$STUB/calls"'

# The model the server calls must be the one Patricia's passport pins.
CHOSEN=review-c run unpinned "$bicep"
check "a modelDeployment that isn't the pinned model: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "modelDeployment .review-c. is DeepSeek-V3.2 1, but Patricia.s passport pins gpt-5.4 2026-03-05" \
   && ! has "== 1/4" && read_only'

# Hosted evaluations. Nothing deployed yet: nothing to read, and it goes on.
run nohosted "$bicep"
check "hosted: nothing deployed yet, so nothing is read" \
  eval 'has "nothing is deployed in rg-test yet, so there are no hosted evaluations" \
   && ! grep -q "^storage" "$STUB/calls" && has "== 1/4"'

# Deployed before the weekly job: its outputs name no data account.
hosted_setup() {  # OUTPUTS-JSON — make the stub's last deployment have these outputs
  mkdir -p "$work/$1"
  echo 1 > "$work/$1/deployed"
  echo "$2" > "$work/$1/outputs"
}
hosted_setup oldtemplate '{"registry": {"value": "reg.azurecr.io"}}'
run oldtemplate "$bicep"
check "hosted: a template from before the weekly job has nothing to read" \
  eval 'has "the deployed template predates the weekly evaluation" && ! grep -q "^storage" "$STUB/calls" && has "== 1/4"'

# Deployed with the job, and its results downloaded: clean, then with drift.
data='{"dataAccount": {"value": "patriciasttest"}}'
hosted_setup hostedclean "$data" && mkdir -p "$work/hostedclean/hosted" && : > "$work/hostedclean/hosted/results.jsonl"
run hostedclean "$bicep"
check "hosted: downloaded with the key in the environment only, checked, and it goes on" \
  eval 'has "hosted: read results.jsonl" && grep -q "^storage file download-batch --account-name patriciasttest --source hive-a2a-data --pattern assurance/\*" "$STUB/calls" \
   && [ "$(cat "$STUB/key")" = s3cretkey ] && ! grep -q s3cretkey "$STUB/calls" && has "== 1/4"'

hosted_setup hosteddrift "$data" && mkdir -p "$work/hosteddrift/hosted" && : > "$work/hosteddrift/hosted/results.jsonl"
HOSTED=drift ANSWER=yes run hosteddrift "$bicep"
check "hosted: drift the weekly evaluation found stops it before any change" \
  eval '[ "$code" -ne 0 ] && has "drift sha256:abc holds promotion" && has "answer it with assurance.sh" \
   && ! has "== 1/4" && ! grep -q "^role definition list" "$STUB/calls"'

hosted_setup hostedfail "$data"
STUB_FAIL="storage file download-batch" ANSWER=yes run hostedfail "$bicep"
check "hosted: a download that fails stops it, rather than skipping the check" \
  eval '[ "$code" -ne 0 ] && has "couldn.t download the hosted evaluations from patriciasttest" && ! has "== 1/4"'

# A job that has gone quiet holds her; one that recorded recently, or is new, doesn't.
ago() {  # DAYS — that long ago, as az prints a creation time
  python3 -c 'import datetime, sys; print((datetime.datetime.now(datetime.timezone.utc)
    - datetime.timedelta(days=float(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%S.1234567+00:00"))' "$1"
}
quiet() {  # CASE JOB-AGE-DAYS [RESULT-AGE-DAYS] — the job, and its newest evaluation if any
  hosted_setup "$1" "$data" && mkdir -p "$work/$1/hosted"
  ago "$2" > "$work/$1/job-created"
  if [ -n "${3:-}" ]; then
    printf '{"id": "x-patricia-weekly-eval", "at": "%s"}\n' "$(ago "$3" | cut -c1-19)Z" > "$work/$1/hosted/results.jsonl"
  fi
}
quiet hostedfresh 30 2
ANSWER=yes run hostedfresh "$bicep"
check "hosted: an evaluation two days old goes on" \
  eval 'has "hosted: last recorded on" && has "== 1/4"'
quiet hostednew 1
ANSWER=yes run hostednew "$bicep"
check "hosted: a job a day old with nothing recorded yet goes on" \
  eval 'has "nothing recorded yet, and the job is 1 day old" && has "== 1/4"'
quiet hostedstale 30 10
ANSWER=yes run hostedstale "$bicep"
check "hosted: an evaluation ten days old stops it before any change" \
  eval '[ "$code" -ne 0 ] && has "hasn.t recorded one in 10 days (the last on" && has "held until the weekly evaluation records again" \
   && ! has "== 1/4" && ! grep -q "^role definition list" "$STUB/calls"'
quiet hostedsilent 30
ANSWER=yes run hostedsilent "$bicep"
check "hosted: a month-old job that never recorded stops it before any change" \
  eval '[ "$code" -ne 0 ] && has "none since the job was created" && ! has "== 1/4"'
quiet hostedjobfail 30 2
STUB_FAIL="containerapp job list" ANSWER=yes run hostedjobfail "$bicep"
check "hosted: a job it can't look up stops it, rather than skipping the check" \
  eval '[ "$code" -ne 0 ] && has "couldn.t read Patricia.s weekly evaluation job" && ! has "== 1/4"'

STUB_FAIL="deployment group list" ANSWER=yes run hostedlist "$bicep"
check "hosted: deployments it can't list stop it, rather than skipping the check" \
  eval '[ "$code" -ne 0 ] && has "couldn.t list the deployments in rg-test" && ! has "== 1/4"'

# Retention: set as its own step after the infrastructure, and not locked unless asked.
ANSWER=yes run retain "$bicep"
check "retention: set to 365 days with protected appends, after the infrastructure, unlocked" \
  eval '[ "$code" -eq 0 ] && has "== 2/4 audit log retention" \
   && grep -q "^storage container immutability-policy create --resource-group rg-test --account-name patricialogtest --container-name audit --period 365 --allow-protected-append-writes true" "$STUB/calls" \
   && has "unlocked, 365 days; to lock it, deploy with --lock-audit-retention" \
   && ! grep -q "immutability-policy lock" "$STUB/calls" && grep -q "^acr build" "$STUB/calls"'

ANSWERS="yes no" run retainno "$bicep"
check "retention: declined, it stops before the image" \
  eval '[ "$code" -ne 0 ] && has "stopped; nothing more was changed" \
   && ! grep -q "immutability-policy create" "$STUB/calls" && ! grep -q "^acr build" "$STUB/calls"'

deploy_args=(--lock-audit-retention)
ANSWERS="yes yes patricialog" run lockwrong "$bicep"
check "lock: the wrong name typed stops it, and the policy stays unlocked" \
  eval '[ "$code" -ne 0 ] && has "Locking can.t be undone" && has "the policy stays unlocked" \
   && ! grep -q "immutability-policy lock" "$STUB/calls" && ! grep -q "^acr build" "$STUB/calls"'

ANSWERS="yes yes patricialogtest yes yes" run lock "$bicep"
check "lock: the account's name typed locks it, against the policy's etag, and it goes on" \
  eval '[ "$code" -eq 0 ] && grep -q "^storage container immutability-policy lock --resource-group rg-test --account-name patricialogtest --container-name audit --if-match \"etag-1\"" "$STUB/calls" \
   && has "patricialogtest/audit: locked" && grep -q "^acr build" "$STUB/calls"'

mkdir -p "$work/locked" && printf 'True\tLocked\t365\tTrue\n' > "$work/locked/policy"
ANSWERS="yes yes yes" run locked "$bicep"
check "lock: a locked policy is left alone, flag or not" \
  eval '[ "$code" -eq 0 ] && has "patricialogtest/audit: locked, 365 days" \
   && ! grep -q "immutability-policy \(create\|lock\)" "$STUB/calls"'
deploy_args=()

# Rollback.
claude='{"deployment": "review-a", "format": "Anthropic", "name": "claude-x", "version": "1", "sku": "GlobalStandard"}'
v1() { git -C "$STUB/repo" rev-parse HEAD~1; }
deploy_args=(--rollback 1 --reason "v2 misreads the Charter" --by usr_test --audit "$work/rb/audit/audit.jsonl")
HISTORY=1 MODELS="[$gpt, $claude]" CHOSEN=review-a ANSWER=yes run rb "$bicep"
check "rollback: deploys v1's commit through every step" \
  eval '[ "$code" -eq 0 ] && has "== rollback: passport v1, at commit $(v1 | cut -c1-12), pinning claude-x 1" \
   && grep -q "^acr build .*hive-a2a:$(v1 | cut -c1-12)" "$STUB/calls" \
   && [ "$(grep -c "^deployment group create" "$STUB/calls")" -eq 2 ]'
check "rollback: the audit log records who, and a record beside it why" \
  eval 'python3 "$here/../../../../knowledge-hive/scripts/check_audit.py" "$STUB/audit/audit.jsonl" >/dev/null \
   && python3 - "$STUB/audit" "$(v1)" <<'"'PY'"'
import json, pathlib, sys
log = pathlib.Path(sys.argv[1])
entry = json.loads((log / "audit.jsonl").read_text().splitlines()[-1])
record = json.loads((log / "rollbacks" / (entry["record"].split(":")[1] + ".json")).read_text())
assert entry["kind"] == "rollback" and entry["by"] == "usr_test" and entry["agent"]["version"] == 1, entry
assert record["reason"] == "v2 misreads the Charter" and record["to"]["commit"] == sys.argv[2], record
assert (record["from"]["version"], record["to"]["version"]) == (2, 1), record
assert "Charter" not in (log / "audit.jsonl").read_text()
PY'
check "rollback: the worktree is removed afterwards" \
  eval '[ "$(git -C "$STUB/repo" worktree list | wc -l)" -eq 1 ]'
check "rollback: the promotion check is v1's, not the checked-out one" \
  eval 'has "patricia: baseline recorded against its pins" && ! has "checked by v2.s promotion check"'

# Stopped at the app: the infrastructure and image stand, but nothing is recorded.
deploy_args=(--rollback 1 --reason "why" --by usr_test --audit "$work/rbstop/audit/audit.jsonl")
HISTORY=1 MODELS="[$gpt, $claude]" CHOSEN=review-a ANSWERS="yes yes yes no" run rbstop "$bicep"
check "rollback: stopped before the app, nothing is recorded" \
  eval '[ "$code" -ne 0 ] && has "== 4/4 app" && has "stopped; nothing more was changed" \
   && [ "$(grep -c "^deployment group create" "$STUB/calls")" -eq 1 ] && [ ! -e "$STUB/audit" ]'

# Deployed, but the audit log can't be written: it fails, saying how to record it.
mkdir -p "$work/rbunrec" && : > "$work/rbunrec/file"
deploy_args=(--rollback 1 --reason "why" --by usr_test --audit "$work/rbunrec/file/audit.jsonl")
HISTORY=1 MODELS="[$gpt, $claude]" CHOSEN=review-a ANSWER=yes run rbunrec "$bicep"
check "rollback: deployed but not recorded, it fails naming the command that records it" \
  eval '[ "$code" -ne 0 ] && [ "$(grep -c "^deployment group create" "$STUB/calls")" -eq 2 ] \
   && has "deployed at passport v1, but the rollback wasn.t recorded" \
   && has "rollback.py record patricia $(v1) --by usr_test" && ! has Traceback'

deploy_args=(--rollback 1 --reason "v2 misreads the Charter" --by usr_test --audit "$work/rbmodel/audit/audit.jsonl")
HISTORY=1 ANSWER=yes run rbmodel "$bicep"
check "rollback: a modelDeployment that isn't the pinned model is refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "modelDeployment .review-b. is gpt-5.4 2026-03-05, but the passport being rolled back to pins claude-x 1" \
   && ! has "== 1/4" && read_only && [ ! -e "$STUB/audit" ]'

deploy_args=(--rollback 1 --reason "why" --by usr_test --audit "$work/rbretired/audit/audit.jsonl")
HISTORY=1 PINNED="claude-old 1" MODELS="[$gpt, {\"deployment\": \"review-a\", \"format\": \"Anthropic\", \"name\": \"claude-old\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  CHOSEN=review-a ANSWER=yes run rbretired "$bicep"
check "rollback: a pinned model the catalog no longer has is refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "review-a: Anthropic claude-old 1 isn.t in the Foundry model catalog" \
   && ! has "== 1/4" && read_only && [ ! -e "$STUB/audit" ]'

deploy_args=(--rollback 2 --reason "why" --by usr_test)
HISTORY=1 ANSWER=yes run rbcurrent "$bicep"
check "rollback: a version that isn't earlier is refused before any az call" \
  eval '[ "$code" -ne 0 ] && has "passport patricia is version 2; roll it back to an earlier version" && [ ! -s "$STUB/calls" ]'

deploy_args=(--rollback 1 --reason "" --by usr_test)
HISTORY=1 ANSWER=yes run rbreason "$bicep"
check "rollback: a missing reason is refused before any az call" \
  eval '[ "$code" -ne 0 ] && has "a rollback needs a reason" && [ ! -s "$STUB/calls" ]'

deploy_args=(--rollback 1 --reason "why" --by usr_test)
HISTORY=1 NO_EVAL_AT_V1=1 ANSWER=yes run rbnoeval "$bicep"
check "rollback: a passport from before trust evaluation is refused before any az call" \
  eval '[ "$code" -ne 0 ] && has "passport v1 predates trust evaluation" && [ ! -s "$STUB/calls" ]'

deploy_args=(--reason "why" rg)
run rbusage "$bicep"
check "a reason without --rollback is a usage error" eval '[ "$code" -eq 2 ] && has "usage:"'
deploy_args=()

[ "$fail" -eq 0 ] && echo "OK  deploy.sh checks passed"
exit "$fail"
