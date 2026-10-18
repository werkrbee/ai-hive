#!/usr/bin/env bash
# Deploy hosted Patricia to Azure. Deploying is an infrastructure change the Queen Bee's
# Charter gates, so this script shows Azure's what-if for each change and goes ahead only
# when you type "yes". Before anything, it checks that every built-in role id main.bicep
# assigns exists, since what-if doesn't, and that every model is generally available in
# the region, by the Foundry model catalog.
#
#   1. the infrastructure, without the app (registry, identity, Foundry, storage, budget)
#   2. the image, built in the new registry from this commit
#   3. the app, running that image
#
# Usage: ./deploy.sh <resource-group> <location> <params.bicepparam>
# Needs: az login; run from anywhere inside the repo, on a clean checkout of the commit
# to deploy.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <resource-group> <location> <params.bicepparam>" >&2
  exit 2
fi
rg=$1 location=$2 params=$3
here=$(cd "$(dirname "$0")" && pwd)
root=$(git -C "$here" rev-parse --show-toplevel)

if [ -n "$(git -C "$root" status --porcelain)" ]; then
  echo "error: the checkout has uncommitted changes; deploy a commit" >&2
  exit 1
fi
tag=$(git -C "$root" rev-parse --short=12 HEAD)

confirm() {
  read -r -p "$1 Type yes to go ahead: " answer
  [ "$answer" = "yes" ] || { echo "stopped; nothing more was changed" >&2; exit 1; }
}

output() {  # $1 = deployment outputs JSON, $2 = output name
  python3 -c 'import json, sys; print(json.loads(sys.argv[1])[sys.argv[2]]["value"])' "$1" "$2"
}

deploy() {  # $1 = image ('' for infrastructure only)
  local args=(--resource-group "$rg" --template-file "$here/main.bicep" --parameters "$params"
              --parameters image="$1")
  az deployment group what-if "${args[@]}" >&2  # shown, not captured
  confirm "Apply the changes above to $rg?"
  az deployment group create "${args[@]}" --query properties.outputs -o json
}

# Azure's what-if doesn't check that a role definition exists, so a wrong built-in role id
# would show as an ordinary create and fail only during the apply, after other resources
# exist. Look up every role main.bicep assigns in the current subscription first.
check_roles() {
  local found assigned refs ref id role
  found=$(sed -n "s/.*subscriptionResourceId('Microsoft.Authorization\/roleDefinitions', *\([^)]*\)).*/\1/p" \
    "$here/main.bicep")
  if [ -z "$found" ]; then
    echo "error: found no role assignments in main.bicep to check" >&2
    exit 1
  fi
  # Every assignment must be one this check reads, or a role written another way would
  # go unchecked.
  assigned=$(grep -c 'roleDefinitionId:' "$here/main.bicep")
  if [ "$(printf '%s\n' "$found" | wc -l)" -ne "$assigned" ]; then
    echo "error: main.bicep assigns $assigned roles, but only the ones written as" \
      "subscriptionResourceId('Microsoft.Authorization/roleDefinitions', <id>) can be checked" >&2
    exit 1
  fi
  refs=$(printf '%s\n' "$found" | sort -u)
  for ref in $refs; do
    case "$ref" in
      \'*) id=${ref//\'/} ;;
      *) id=$(sed -n "s/^var $ref = '\([^']*\)'.*/\1/p" "$here/main.bicep") ;;
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
# which must be one of them.
check_models() {
  local region tmp kind
  kind=$(awk "/^resource ai 'Microsoft.CognitiveServices\/accounts@/{f=1} f && /^}/{exit} f && /^  kind: /{gsub(/[' ]|kind:/, \"\"); print; exit}" \
    "$here/main.bicep")
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
  if ! python3 - "$tmp/params.json" "$tmp/catalog.json" "$region" "$kind" "$here/main.bicep" <<'PY'
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

echo "== role ids"
check_roles
echo "== models"
check_models

echo "== 1/3 infrastructure"
if [ "$(az group exists --name "$rg")" != "true" ]; then
  confirm "Create resource group $rg in $location?"
  az group create --name "$rg" --location "$location" -o none
fi
outputs=$(deploy "")
registry=$(output "$outputs" registry)

echo "== 2/3 image hive-a2a:$tag in $registry"
confirm "Build and push the image to $registry?"
az acr build --registry "${registry%%.*}" --image "hive-a2a:$tag" \
  --file "$root/hives/agents-hive/deploy/azure/Dockerfile" "$root"

echo "== 3/3 app"
outputs=$(deploy "$registry/hive-a2a:$tag")
echo "Agent Card: $(output "$outputs" agentCard)"
