#!/usr/bin/env bash
# Exercise deploy.sh's checks against a stubbed az. A passport the promotion check refuses
# stops before any az call. Role ids: the current ids pass and
# reach the first what-if; a wrong id, or a lookup that fails, stops before any what-if or
# change. Models: generally available ones pass, from any publisher, each named with the
# API the server would use and the chosen one marked; one that is preview, missing from
# the catalog, offered only for another account kind, without chat completions or not
# offered with its sku stops before the what-if, as does a modelDeployment that names no
# model. A what-if that fails stops without asking to apply anything. Each case runs
# deploy.sh from a throwaway git checkout, since it deploys only a clean one. Bash 3.2
# safe; run it with /bin/bash on macOS.
#
# Usage: tests/deploy_test.sh           (from hives/agents-hive/deploy/azure, or anywhere)
set -u

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0

# The stub. $STUB/roles holds the subscription's role definitions ("id name"),
# $STUB/params.json what build-params prints and $STUB/catalog.json the region's model
# catalog; every call is appended to $STUB/calls. STUB_FAIL, when set, is a pattern; a
# call whose arguments match it fails.
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
  "deployment group what-if"*) echo "what-if shown" ;;
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
# (default no) at the first prompt
run() {
  export STUB="$work/$1"
  local repo="$STUB/repo" dir="$STUB/repo/hives/agents-hive/deploy/azure"
  mkdir -p "$dir"
  printf '%s\n' "7f951dda-4ed3-4680-a7ca-43fe172d538d AcrPull" \
    "a97b65f3-24c7-4388-baec-2e87135dc908 Cognitive Services User" \
    "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd Cognitive Services OpenAI User" > "$STUB/roles"
  : > "$STUB/calls"
  cp "$work/catalog.json" "$STUB/catalog.json"
  python3 -c 'import json, sys; models = json.loads(sys.argv[1]); print(json.dumps({"parametersJson": json.dumps(
    {"parameters": {"models": {"value": models}, "modelDeployment": {"value": sys.argv[2] or models[0]["deployment"]}}})}))' \
    "${MODELS:-[$gpt, $deepseek]}" "${CHOSEN:-}" > "$STUB/params.json"
  cp "$here/../deploy.sh" "$dir/"
  cp "$2" "$dir/main.bicep"
  # The promotion check, stubbed: it passes unless $PROMOTION is "refused".
  mkdir -p "$repo/hives/agents-hive/scripts"
  cat > "$repo/hives/agents-hive/scripts/trust_eval.py" <<'PY'
import os, sys
if os.environ.get("PROMOTION") == "refused":
    sys.exit("refused: passport patricia v4's baseline was recorded against other pins")
print(f"{sys.argv[2]}: baseline recorded against its pins, and no drift holds it")
PY
  git -C "$repo" init -q
  git -C "$repo" add -A
  git -C "$repo" -c user.name=test -c user.email=test@example.com commit -q -m test
  out=$(printf '%s\n' "${ANSWER:-no}" | PATH="$work/bin:$PATH" /bin/bash "$dir/deploy.sh" rg-test eastus2 p.bicepparam 2>&1)
  code=$?
}
check() {  # LABEL CONDITION...
  local label="$1"; shift
  if "$@"; then echo "pass  $label"; else echo "FAIL  $label"; printf '%s\n' "$out" | sed 's/^/      /'; fail=1; fi
}
has() { printf '%s\n' "$out" | grep -q -- "$1"; }
# Only role lookups ran: no what-if, no resource group, no deployment.
only_lookups() { ! grep -qv "^role definition list" "$STUB/calls"; }

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
  eval 'has "== 1/3 infrastructure" && grep -q "^deployment group what-if" "$STUB/calls"'
check "a promotable passport: checked first, for Patricia" \
  eval 'has "patricia: baseline recorded against its pins"'

# The id the first deploy had wrong: refused, naming it, before anything else.
sed 's/7f951dda-4ed3-4680-a7ca-43fe172d538d/7f951dde-4ef9-41c1-b0ac-8f2d6ec5c76b/' "$bicep" > "$work/wrong.bicep"
run wrong "$work/wrong.bicep"
check "wrong id: refused before any what-if, naming the id" \
  eval '[ "$code" -ne 0 ] && has "role definition 7f951dde-4ef9-41c1-b0ac-8f2d6ec5c76b (acrPull) doesn.t exist" \
   && ! has "== 1/3" && only_lookups'

# A lookup that fails is a refusal too, not a pass.
STUB_FAIL="role definition list" run lookup "$bicep"
check "failed lookup: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "couldn.t look up role definition" && ! has "== 1/3" && only_lookups'

# A main.bicep the check can't read is refused rather than passed unchecked.
sed '/^var acrPull = /d' "$bicep" > "$work/unnamed.bicep"
run unnamed "$work/unnamed.bicep"
check "role var not found: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "can.t find the role id acrPull names" && [ ! -s "$STUB/calls" ]'

sed 's/subscriptionResourceId(.Microsoft.Authorization\/roleDefinitions., \([A-Za-z]*\))/\1/' \
  "$bicep" > "$work/none.bicep"
run none "$work/none.bicep"
check "no readable role assignments: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "found no role assignments" && [ ! -s "$STUB/calls" ]'

# An assignment written another way is refused, not skipped.
awk '!done && /roleDefinitionId: subscriptionResourceId/ {sub(/subscriptionResourceId\([^)]*\)/, "acrPull"); done=1} {print}' \
  "$bicep" > "$work/other.bicep"
run other "$work/other.bicep"
check "an assignment it can't read: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "assigns 3 roles, but only" && [ ! -s "$STUB/calls" ]'

# Models: the catalog is the source of truth.
read_only() { ! grep -qvE "^(role definition list|group (exists|show)|bicep build-params|cognitiveservices model list)" "$STUB/calls"; }

run ga "$bicep"
check "GA models: each passes, from any publisher, and deploy.sh goes on" \
  eval 'has "review-b: OpenAI gpt-5.4 2026-03-05: GenerallyAvailable, GlobalStandard" \
   && has "review-c: DeepSeek DeepSeek-V3.2 1: GenerallyAvailable, GlobalStandard" && has "== 1/3"'
check "GA models: each names its API, and the chosen one is marked" \
  eval 'has "review-b: OpenAI gpt-5.4 2026-03-05: GenerallyAvailable, GlobalStandard, via Chat Completions (modelDeployment: the server calls this one)" \
   && has "review-c: DeepSeek DeepSeek-V3.2 1: GenerallyAvailable, GlobalStandard, via Chat Completions$"'
check "GA models: the catalog read is for the resource group's region" \
  grep -q "^cognitiveservices model list --location eastus2" "$STUB/calls"

MODELS="[$gpt, {\"deployment\": \"review-x\", \"format\": \"xAI\", \"name\": \"grok-next\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run preview "$bicep"
check "preview model: refused before any what-if, with its lifecycle status" \
  eval '[ "$code" -ne 0 ] && has "review-x: xAI grok-next 1 is Preview in eastus2; only GenerallyAvailable models deploy" \
   && ! has "== 1/3" && read_only'

MODELS="[{\"deployment\": \"review-z\", \"format\": \"Meta\", \"name\": \"llama-none\", \"version\": \"9\", \"sku\": \"GlobalStandard\"}]" \
  run missing "$bicep"
check "model not in the catalog: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "review-z: Meta llama-none 9 isn.t in the Foundry model catalog for eastus2" \
   && ! has "== 1/3" && read_only'

MODELS="[{\"deployment\": \"review-m\", \"format\": \"Mistral AI\", \"name\": \"mistral-x\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run sku "$bicep"
check "sku not offered: refused before any what-if, naming what is" \
  eval '[ "$code" -ne 0 ] && has "isn.t offered as GlobalStandard in eastus2 (offered: Standard)" \
   && ! has "== 1/3" && read_only'

MODELS="[{\"deployment\": \"review-r\", \"format\": \"OpenAI\", \"name\": \"gpt-codex\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run responses "$bicep"
check "model without chat completions: refused before any what-if, naming what it does" \
  eval '[ "$code" -ne 0 ] && has "review-r: OpenAI gpt-codex 1 doesn.t do chat completions, so the server can.t call it (it does: responses)" \
   && ! has "== 1/3" && read_only'

MODELS="[{\"deployment\": \"review-o\", \"format\": \"OpenAI\", \"name\": \"gpt-legacy\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run kind "$bicep"
check "model offered only for another account kind: refused before any what-if, naming it" \
  eval '[ "$code" -ne 0 ] && has "review-o: OpenAI gpt-legacy 1 is offered in eastus2 only for OpenAI accounts, not AIServices" \
   && ! has "== 1/3" && read_only'

MODELS="[{\"deployment\": \"review-s\", \"format\": \"OpenAI\", \"name\": \"gpt-split\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run splitkind "$bicep"
check "sku offered only under another account kind: refused, naming what AIServices offers" \
  eval '[ "$code" -ne 0 ] && has "review-s: OpenAI gpt-split 1 isn.t offered as GlobalStandard in eastus2 (offered: Standard)" \
   && ! has "== 1/3" && read_only'

awk "/^resource ai 'Microsoft.CognitiveServices/{f=1} f && /^}/{f=0} !(f && /^  kind: /)" "$bicep" > "$work/nokind.bicep"
run nokind "$work/nokind.bicep"
check "account kind not found in main.bicep: refused before reading the catalog" \
  eval '[ "$code" -ne 0 ] && has "can.t find the Foundry account.s kind" && ! grep -q "^cognitiveservices" "$STUB/calls"'

MODELS="[$gpt, {\"deployment\": \"review-a\", \"format\": \"Anthropic\", \"name\": \"claude-x\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
CHOSEN=review-a run messages "$bicep"
check "an Anthropic model is shown via Messages, by main.bicep's messagesFormats" \
  eval 'has "review-a: Anthropic claude-x 1: GenerallyAvailable, GlobalStandard, via Messages (modelDeployment: the server calls this one)" \
   && has "review-b: OpenAI gpt-5.4 2026-03-05: GenerallyAvailable, GlobalStandard, via Chat Completions$"'

sed '/^var messagesFormats = /d' "$bicep" > "$work/norule.bicep"
run norule "$work/norule.bicep"
check "messagesFormats not found in main.bicep: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "can.t find messagesFormats in main.bicep" && ! has "== 1/3"'

sed "s/^var messagesFormats = \[/var  messagesFormats=[/" "$bicep" > "$work/spaced.bicep"
MODELS="[$gpt, {\"deployment\": \"review-a\", \"format\": \"Anthropic\", \"name\": \"claude-x\", \"version\": \"1\", \"sku\": \"GlobalStandard\"}]" \
  run spaced "$work/spaced.bicep"
check "messagesFormats spaced differently: still read" \
  eval 'grep -q "^var  messagesFormats=\[" "$STUB/repo/hives/agents-hive/deploy/azure/main.bicep" \
   && has "review-a: Anthropic claude-x 1: GenerallyAvailable, GlobalStandard, via Messages$"'

CHOSEN=review-z run nochosen "$bicep"
check "modelDeployment names no model: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "modelDeployment .review-z. isn.t the deployment of any entry in models" \
   && ! has "== 1/3" && read_only'

STUB_FAIL="cognitiveservices model list" run nocatalog "$bicep"
check "catalog unreadable: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "couldn.t read the Foundry model catalog for eastus2" && ! has "== 1/3" && read_only'

# A what-if that fails shows no plan, so nothing is applied even when the answer is yes.
STUB_FAIL="deployment group what-if" ANSWER=yes run whatiffails "$bicep"
check "what-if fails: stops without asking, and nothing is applied" \
  eval '[ "$code" -ne 0 ] && has "the what-if failed, so there.s no plan to approve" \
   && ! grep -q "^deployment group create" "$STUB/calls"'

[ "$fail" -eq 0 ] && echo "OK  deploy.sh checks passed"
exit "$fail"
