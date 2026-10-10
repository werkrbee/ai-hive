#!/usr/bin/env bash
# Deploy hosted Patricia to Azure. Deploying is an infrastructure change the Queen Bee's
# Charter gates, so this script shows Azure's what-if for each change and goes ahead only
# when you type "yes".
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
