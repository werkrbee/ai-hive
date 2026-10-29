#!/usr/bin/env bash
# Deploy hosted Patricia to Azure. Deploying is an infrastructure change the Queen Bee's
# Charter gates, so this script shows Azure's what-if for each change and goes ahead only
# when you type "yes". Before anything, it checks that Patricia's passport may be promoted
# (its trust evaluation's baseline was recorded against its exact pins, and no drift holds
# it in the review queue, here or in what her weekly evaluation recorded in Azure, and
# that evaluation has recorded within eight days), that
# every built-in role id main.bicep assigns exists, since what-if doesn't, and that every
# model is generally available in the region, by the Foundry model catalog, and that the
# one the server calls is the model her passport pins.
#
#   1. the infrastructure, without the app (registry, identity, Foundry, storage, the
#      audit log's storage, budget)
#   2. the audit log's retention policy: 365 days, protected append writes allowed; it is
#      locked, which can't be undone, only with --lock-audit-retention
#   3. the image, built in the new registry from this commit
#   4. the app and the weekly evaluation job, running that image
#
# --rollback VERSION rolls Patricia back to an earlier passport version instead: it
# deploys the newest commit at which her passport was VERSION, from a temporary worktree,
# with the model, prompt files and policy that passport pins. The same checks run against
# that commit, and modelDeployment must be the model it pins, so a model the catalog has
# since retired stops it. It warns of findings recorded since against those pins, which
# that commit's promotion check can't see. Once the app is deployed, the audit log records
# who rolled her back (--by, or WORKFLOWS_HIVE_ACTOR) and the digest of a record, beside
# the log, that keeps the reason.
#
# Usage: ./deploy.sh [--lock-audit-retention]
#                    [--rollback VERSION --reason TEXT [--by ACTOR-ID] [--audit PATH]]
#                    <resource-group> <location> <params.bicepparam>
# Needs: az login; run from anywhere inside the repo, on a clean checkout of the commit
# to deploy.
set -euo pipefail

usage() {
  echo "usage: $0 [--lock-audit-retention] [--rollback VERSION --reason TEXT [--by ACTOR-ID]" \
    "[--audit PATH]] <resource-group> <location> <params.bicepparam>" >&2
  exit 2
}
rollback='' reason='' by=${WORKFLOWS_HIVE_ACTOR:-} audit='' lock=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --lock-audit-retention) lock=1; shift ;;
    --rollback|--reason|--by|--audit)
      [ "$#" -ge 2 ] || usage
      case "$1" in
        --rollback) rollback=$2 ;; --reason) reason=$2 ;; --by) by=$2 ;; --audit) audit=$2 ;;
      esac
      shift 2 ;;
    -*) usage ;;
    *) break ;;
  esac
done
if [ "$#" -ne 3 ] || { [ -z "$rollback" ] && [ -n "$reason$audit" ]; }; then
  usage
fi
rg=$1 location=$2 params=$3
here=$(cd "$(dirname "$0")" && pwd)
root=$(git -C "$here" rev-parse --show-toplevel)

if [ -n "$(git -C "$root" status --porcelain)" ]; then
  echo "error: the checkout has uncommitted changes; deploy a commit" >&2
  exit 1
fi

worktree='' hosted=''
cleanup() {
  if [ -n "$worktree" ]; then
    git -C "$root" worktree remove --force "$worktree/src" 2>/dev/null; rm -rf "$worktree"
  fi
  if [ -n "$hosted" ]; then rm -rf "$hosted"; fi
}
trap cleanup EXIT

# What is deployed: this checkout, or for a rollback, the earlier commit in a worktree.
src=$root pinned=''
if [ -n "$rollback" ]; then
  plan=$(python3 "$root/hives/agents-hive/scripts/rollback.py" plan patricia "$rollback" \
    --by "$by" --reason "$reason") || exit 1
  read -r commit pinned_name pinned_version <<< "$plan"
  pinned="$pinned_name $pinned_version"
  worktree=$(mktemp -d)
  git -C "$root" worktree add --quiet --detach "$worktree/src" "$commit"
  src=$worktree/src
  echo "== rollback: passport v$rollback, at commit ${commit:0:12}, pinning $pinned"
else
  # The model the server calls must be the one her passport pins, as for a rollback.
  pinned=$(python3 -c 'import json, sys; m = json.load(open(sys.argv[1]))["pins"]["model"]
print(m["name"], m["version"])' "$root/hives/agents-hive/passports/patricia/passport.json") || {
    echo "error: can't read the model Patricia's passport pins; nothing was changed" >&2
    exit 1
  }
fi
azure=$src/hives/agents-hive/deploy/azure
tag=$(git -C "$src" rev-parse --short=12 HEAD)

confirm() {
  read -r -p "$1 Type yes to go ahead: " answer
  [ "$answer" = "yes" ] || { echo "stopped; nothing more was changed" >&2; exit 1; }
}

output() {  # $1 = deployment outputs JSON, $2 = output name; empty when there is none
  python3 -c 'import json, sys; print((json.loads(sys.argv[1] or "{}").get(sys.argv[2]) or {}).get("value", ""))' \
    "$1" "$2"
}

deploy() {  # $1 = image ('' for infrastructure only)
  local args=(--resource-group "$rg" --template-file "$azure/main.bicep" --parameters "$params"
              --parameters image="$1")
  # deploy runs inside $(...), where bash doesn't apply set -e (and 3.2 has no
  # inherit_errexit), so a failed what-if is checked here; otherwise it would still ask
  # to apply a plan that was never shown.
  if ! az deployment group what-if "${args[@]}" >&2; then  # shown, not captured
    echo "error: the what-if failed, so there's no plan to approve; nothing more was changed" >&2
    exit 1
  fi
  confirm "Apply the changes above to $rg?"
  az deployment group create "${args[@]}" --query properties.outputs -o json
}

# Azure's what-if doesn't check that a role definition exists, so a wrong built-in role id
# would show as an ordinary create and fail only during the apply, after other resources
# exist. Look up every role main.bicep assigns in the current subscription first.
check_roles() {
  local found assigned refs ref id role
  found=$(sed -n "s/.*subscriptionResourceId('Microsoft.Authorization\/roleDefinitions', *\([^)]*\)).*/\1/p" \
    "$azure/main.bicep")
  if [ -z "$found" ]; then
    echo "error: found no role assignments in main.bicep to check" >&2
    exit 1
  fi
  # Every assignment must be one this check reads, or a role written another way would
  # go unchecked.
  assigned=$(grep -c 'roleDefinitionId:' "$azure/main.bicep")
  if [ "$(printf '%s\n' "$found" | wc -l)" -ne "$assigned" ]; then
    echo "error: main.bicep assigns $assigned roles, but only the ones written as" \
      "subscriptionResourceId('Microsoft.Authorization/roleDefinitions', <id>) can be checked" >&2
    exit 1
  fi
  refs=$(printf '%s\n' "$found" | sort -u)
  for ref in $refs; do
    case "$ref" in
      \'*) id=${ref//\'/} ;;
      *) id=$(sed -n "s/^var $ref = '\([^']*\)'.*/\1/p" "$azure/main.bicep") ;;
    esac
    if [ -z "$id" ]; then
      echo "error: can't find the role id $ref names in main.bicep" >&2
      exit 1
    fi
    role=$(az role definition list --name "$id" --query "[].roleName" -o tsv) || {
      echo "error: couldn't look up role definition $id ($ref)" >&2
      exit 1
    }
    if [ -z "$role" ]; then
      echo "error: role definition $id ($ref) doesn't exist; fix it in main.bicep" >&2
      exit 1
    fi
    echo "$ref: $id ($role)"
  done
}

# The Foundry model catalog is the source of truth for what can be deployed: every entry
# in models must be GenerallyAvailable in the region, by format, name and version, do chat
# completions (the server's two APIs, Messages and Chat Completions, both need it), and be
# offered there with its sku. Preview and retiring models are refused here, before the
# what-if, the same rule as for Azure API versions. The catalog lists a model once per
# account kind, and what each kind offers can differ, so only the rows for the kind of
# account main.bicep deploys count. Each model's line names the API the server would use
# with it, by main.bicep's messagesFormats, and marks the one modelDeployment chooses,
# which must be one of them and the model Patricia's passport pins, by name and version:
# for a rollback, the earlier passport's, so a model since retired can't come back.
check_models() {
  local region tmp kind
  kind=$(awk "/^resource ai 'Microsoft.CognitiveServices\/accounts@/{f=1} f && /^}/{exit} f && /^  kind: /{gsub(/[' ]|kind:/, \"\"); print; exit}" \
    "$azure/main.bicep")
  if [ -z "$kind" ]; then
    echo "error: can't find the Foundry account's kind in main.bicep" >&2
    exit 1
  fi
  region=$location
  if [ "$(az group exists --name "$rg")" = "true" ]; then
    region=$(az group show --name "$rg" --query location -o tsv)
  fi
  tmp=$(mktemp -d)
  if ! az bicep build-params --file "$params" --stdout > "$tmp/params.json"; then
    echo "error: couldn't read the models in $params" >&2
    rm -rf "$tmp"; exit 1
  fi
  if ! az cognitiveservices model list --location "$region" -o json > "$tmp/catalog.json"; then
    echo "error: couldn't read the Foundry model catalog for $region" >&2
    rm -rf "$tmp"; exit 1
  fi
  if ! python3 - "$tmp/params.json" "$tmp/catalog.json" "$region" "$kind" "$azure/main.bicep" "$pinned" \
      "${rollback:+the passport being rolled back to}" <<'PY'
import json, re, sys

params = json.loads(json.load(open(sys.argv[1]))["parametersJson"])["parameters"]
catalog, region, kind = json.load(open(sys.argv[2])), sys.argv[3], sys.argv[4]
rule = re.search(r"^var\s+messagesFormats\s*=\s*\[([^\]]*)\]", open(sys.argv[5]).read(), re.M)
if not rule:
    print("error: can't find messagesFormats in main.bicep, the rule for which API a model uses", file=sys.stderr)
    sys.exit(1)
messages_formats = re.findall(r"'([^']*)'", rule.group(1))
chosen = (params.get("modelDeployment") or {}).get("value")
if chosen not in [m.get("deployment") for m in params["models"]["value"]]:
    print(f"error: modelDeployment {chosen!r} isn't the deployment of any entry in models", file=sys.stderr)
    sys.exit(1)
bad = False
entry = next(m for m in params["models"]["value"] if m.get("deployment") == chosen)
if f"{entry.get('name')} {entry.get('version')}" != sys.argv[6]:
    whose = sys.argv[7] or "Patricia's passport"
    print(f"error: modelDeployment {chosen!r} is {entry.get('name')} {entry.get('version')}, but {whose} "
          f"pins {sys.argv[6]}; point modelDeployment at a deployment of it", file=sys.stderr)
    bad = True
for m in params["models"]["value"]:
    if not all(isinstance(m.get(k), str) for k in ("deployment", "format", "name", "version", "sku")):
        print(f"error: each models entry needs deployment, format, name, version and sku: {m}", file=sys.stderr)
        bad = True
        continue
    label = f"{m['deployment']}: {m['format']} {m['name']} {m['version']}"
    rows = [c for c in catalog
            if (c["model"]["format"], c["model"]["name"], c["model"]["version"]) == (m["format"], m["name"], m["version"])]
    found = [c["model"] for c in rows if c.get("kind") == kind]
    if rows and not found:
        others = ", ".join(sorted({str(c.get("kind")) for c in rows}))
        print(f"error: {label} is offered in {region} only for {others} accounts, not {kind}, the kind main.bicep deploys", file=sys.stderr)
        bad = True
        continue
    statuses = sorted({f["lifecycleStatus"] for f in found})
    skus = sorted({s["name"] for f in found for s in f.get("skus") or []})
    if not found:
        print(f"error: {label} isn't in the Foundry model catalog for {region}", file=sys.stderr)
    elif "GenerallyAvailable" not in statuses:
        print(f"error: {label} is {', '.join(statuses)} in {region}; only GenerallyAvailable models deploy", file=sys.stderr)
    elif not any((f.get("capabilities") or {}).get("chatCompletion") == "true" for f in found):
        caps = sorted({c for f in found for c, v in (f.get("capabilities") or {}).items() if v == "true"})
        print(f"error: {label} doesn't do chat completions, so the server can't call it"
              f" (it does: {', '.join(caps) or 'nothing listed'})", file=sys.stderr)
    elif m["sku"] not in skus:
        print(f"error: {label} isn't offered as {m['sku']} in {region} (offered: {', '.join(skus)})", file=sys.stderr)
    else:
        api = "Messages" if m["format"] in messages_formats else "Chat Completions"
        mark = " (modelDeployment: the server calls this one)" if m["deployment"] == chosen else ""
        print(f"{label}: GenerallyAvailable, {m['sku']}, via {api}{mark}")
        continue
    bad = True
sys.exit(1 if bad else 0)
PY
  then
    rm -rf "$tmp"; exit 1
  fi
  rm -rf "$tmp"
}

# A change to Patricia is promoted only once her trust evaluation has passed on its exact
# pins, and while no drift waits for a person (hives/agents-hive/scripts/trust_eval.py).
# A rollback checks the earlier passport with the check as it was at that commit, against
# the results recorded then, since that passport's baseline still applies.
echo "== passport"
if [ ! -f "$src/hives/agents-hive/scripts/trust_eval.py" ]; then
  echo "error: passport v$rollback predates trust evaluation, so it can't be promoted; nothing was changed" >&2
  exit 1
fi
if ! python3 "$src/hives/agents-hive/scripts/trust_eval.py" promotion patricia; then
  echo "error: Patricia's passport can't be promoted; nothing was changed" >&2
  exit 1
fi

# Patricia's weekly evaluation records its results and findings on the deployment's file
# share, so drift it found holds promotion only once read from there. They are downloaded,
# read-only, and checked as the local ones were. A rollback skips this: the earlier
# passport's check can't read them, and answering drift is what a rollback is for.
# Weekly, with a day's grace; a less frequent evalSchedule needs this raised.
HOSTED_MAX_DAYS=8
hosted_check() {
  local deployed outputs account key created
  if [ "$(az group exists --name "$rg")" != "true" ]; then
    echo "nothing is deployed in $rg yet, so there are no hosted evaluations"
    return
  fi
  deployed=$(az deployment group list --resource-group "$rg" --query "length([?name=='main'])" -o tsv) || {
    echo "error: couldn't list the deployments in $rg; nothing was changed" >&2
    exit 1
  }
  if [ "$deployed" = "0" ]; then
    echo "nothing is deployed in $rg yet, so there are no hosted evaluations"
    return
  fi
  outputs=$(az deployment group show --resource-group "$rg" --name main --query properties.outputs -o json) || {
    echo "error: couldn't read the last deployment in $rg; nothing was changed" >&2
    exit 1
  }
  account=$(output "$outputs" dataAccount)
  if [ -z "$account" ]; then
    echo "the deployed template predates the weekly evaluation, so there are no hosted evaluations"
    return
  fi
  # The share takes the account key; it is passed in the environment, never an argument.
  if ! key=$(az storage account keys list --resource-group "$rg" --account-name "$account" \
      --query '[0].value' -o tsv) || [ -z "$key" ]; then
    echo "error: couldn't read $account's key to download the hosted evaluations; nothing was changed" >&2
    exit 1
  fi
  hosted=$(mktemp -d)
  if ! AZURE_STORAGE_KEY=$key az storage file download-batch --account-name "$account" \
      --source hive-a2a-data --pattern 'assurance/*' --destination "$hosted" -o none; then
    echo "error: couldn't download the hosted evaluations from $account; nothing was changed" >&2
    exit 1
  fi
  if ! python3 "$src/hives/agents-hive/scripts/trust_eval.py" promotion patricia \
      --queue-dir "$hosted/assurance/queue" --results "$hosted/assurance/results.jsonl"; then
    echo "error: what Patricia's weekly evaluation found holds her passport; answer it with" \
      "assurance.sh; nothing was changed" >&2
    exit 1
  fi
  # A job that stops recording, because its audit push fails, say, leaves nothing for the
  # check above to find, so its silence holds her too: the newest evaluation, or the job's
  # creation if it hasn't recorded one yet, must be within HOSTED_MAX_DAYS.
  if ! created=$(az containerapp job list --resource-group "$rg" \
      --query "[?ends_with(name, '-eval')].systemData.createdAt | [0]" -o tsv); then
    echo "error: couldn't read Patricia's weekly evaluation job in $rg; nothing was changed" >&2
    exit 1
  fi
  if [ -z "$created" ]; then
    echo "the weekly evaluation job isn't deployed yet, so it has nothing to have recorded"
    return
  fi
  if ! python3 - "$hosted/assurance/results.jsonl" "$created" "$HOSTED_MAX_DAYS" <<'PY'
import datetime, json, re, sys
from pathlib import Path

def when(text):  # "2026-10-27", "2026-10-27T01:29:05Z" or az's "2026-10-27T01:29:05.1234567+00:00"
    # Python before 3.11 takes neither Z nor more than six digits of a second.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text.replace("Z", "+00:00"))
    t = datetime.datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)

results, created, days = Path(sys.argv[1]), when(sys.argv[2]), int(sys.argv[3])
lines = results.read_text().splitlines() if results.is_file() else []
newest = max((when(json.loads(line)["at"]) for line in lines if line.strip()), default=None)
now = datetime.datetime.now(datetime.timezone.utc)
age = (now - (newest or created)).days
ago = f"{age} day{'' if age == 1 else 's'}"
if now - (newest or created) <= datetime.timedelta(days=days):
    print(f"hosted: last recorded on {newest:%Y-%m-%d}" if newest
          else f"hosted: nothing recorded yet, and the job is {ago} old")
    sys.exit(0)
print(f"error: Patricia's weekly evaluation hasn't recorded one in {ago}"
      + (f" (the last on {newest:%Y-%m-%d})" if newest else ", none since the job was created")
      + f", more than {days}; see why in the job's execution history", file=sys.stderr)
sys.exit(1)
PY
  then
    echo "error: her passport is held until the weekly evaluation records again; nothing was changed" >&2
    exit 1
  fi
}

# The audit log's immutable copy is held by a time-based retention policy on its container
# (docs/assurance-loop.md). Setting it, and changing it while it is unlocked, is one gated
# step; locking it is another, taken only with --lock-audit-retention and the account's
# name typed, because a locked policy can't be shortened or removed, and its account and
# this resource group can't be deleted, until the period ends.
RETENTION_DAYS=365
retention() {  # $1 = deployment outputs JSON
  local account container info has state days appends etag answer
  account=$(output "$1" auditAccount) container=$(output "$1" auditContainer)
  if [ -z "$account" ]; then
    echo "this template has no audit log storage; nothing to do"
    return
  fi
  local q='[hasImmutabilityPolicy, immutabilityPolicy.state, immutabilityPolicy.immutabilityPeriodSinceCreationInDays'
  q+=', immutabilityPolicy.allowProtectedAppendWrites]'
  info=$(az storage container-rm show --resource-group "$rg" --storage-account "$account" \
    --name "$container" --query "$q" -o tsv) || {
    echo "error: couldn't read $account/$container's retention policy" >&2
    exit 1
  }
  # az's tsv prints booleans as True and False.
  read -r has state days appends <<< "$(printf '%s' "$info" | tr '\n\t' '  ')"
  has=$(printf '%s' "$has" | tr '[:upper:]' '[:lower:]')
  appends=$(printf '%s' "$appends" | tr '[:upper:]' '[:lower:]')
  if [ "$has" != "true" ] || { [ "$state" != "Locked" ] \
      && { [ "$days" != "$RETENTION_DAYS" ] || [ "$appends" != "true" ]; }; }; then
    if [ "$has" = "true" ]; then
      echo "$account/$container's policy is $state, $days days, protected appends $appends"
    fi
    confirm "Set a $RETENTION_DAYS-day time-based retention policy on $account/$container, allowing protected append writes? Until it is locked, it can be removed."
    az storage container immutability-policy create --resource-group "$rg" --account-name "$account" \
      --container-name "$container" --period "$RETENTION_DAYS" --allow-protected-append-writes true -o none
    state=Unlocked
  fi
  if [ "$state" = "Locked" ]; then
    echo "$account/$container: locked, $days days, protected appends allowed"
    return
  fi
  if [ -z "$lock" ]; then
    echo "$account/$container: unlocked, $RETENTION_DAYS days; to lock it, deploy with --lock-audit-retention"
    return
  fi
  echo "Locking can't be undone. For $RETENTION_DAYS days from each blob's creation, nobody, the" \
    "subscription's owner included, can change or delete what $container holds, shorten or" \
    "remove the policy, or delete $account or the resource group $rg."
  read -r -p "Type the account name, $account, to lock it: " answer
  [ "$answer" = "$account" ] || { echo "stopped; the policy stays unlocked" >&2; exit 1; }
  etag=$(az storage container immutability-policy show --resource-group "$rg" --account-name "$account" \
    --container-name "$container" --query etag -o tsv) || exit 1
  az storage container immutability-policy lock --resource-group "$rg" --account-name "$account" \
    --container-name "$container" --if-match "$etag" -o none
  echo "$account/$container: locked"
}

if [ -z "$rollback" ]; then
  echo "== hosted evaluations"
  hosted_check
fi

echo "== role ids"
check_roles
echo "== models"
check_models

echo "== 1/4 infrastructure"
if [ "$(az group exists --name "$rg")" != "true" ]; then
  confirm "Create resource group $rg in $location?"
  az group create --name "$rg" --location "$location" -o none
fi
outputs=$(deploy "")
registry=$(output "$outputs" registry)

echo "== 2/4 audit log retention"
retention "$outputs"

echo "== 3/4 image hive-a2a:$tag in $registry"
confirm "Build and push the image to $registry?"
az acr build --registry "${registry%%.*}" --image "hive-a2a:$tag" \
  --file "$azure/Dockerfile" "$src"

echo "== 4/4 app and weekly evaluation job"
outputs=$(deploy "$registry/hive-a2a:$tag")
echo "Agent Card: $(output "$outputs" agentCard)"

# The app is deployed by now, so a rollback that can't be recorded says so, and how to
# record it, rather than leaving the deploy unrecorded without a word.
rollback_py=$root/hives/agents-hive/scripts/rollback.py
if [ -n "$rollback" ] && ! python3 "$rollback_py" record patricia "$commit" --by "$by" \
    --reason "$reason" ${audit:+--audit "$audit"}; then
  echo "error: Patricia is deployed at passport v$rollback, but the rollback wasn't" \
    "recorded; fix the cause above, then run: python3 $rollback_py record patricia" \
    "$commit --by $by --reason <the reason>${audit:+ --audit $audit}" >&2
  exit 1
fi
