#!/usr/bin/env bash
# Create the Entra ID app registrations for hosted Patricia: one API app that issues
# access tokens for the server, and one client app per calling product, each granted the
# API's Review.Request app role. Safe to re-run: existing apps are found by name and reused.
#
# It creates no secrets. Each product's owner adds a credential to their own app
# (preferably a certificate or a federated credential) and keeps it in that product's
# secret store.
#
# Usage: ./entra.sh lineup singularity
# Needs: az login, with rights to create app registrations in the tenant. It reuses an
# existing app only when exactly one has that display name and you own it, and asks before
# changing anything.
set -euo pipefail

API_NAME="patricia-a2a-api"
ROLE_VALUE="Review.Request"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <caller> [<caller> ...]   e.g. $0 lineup singularity" >&2
  exit 2
fi

me=$(az ad signed-in-user show --query id -o tsv)

app_id_for() {  # the appId of the one app with exactly this display name that you own, or nothing
  local ids owned
  ids=$(az ad app list --filter "displayName eq '$1'" --query "[].appId" -o tsv)
  case "$(printf '%s' "$ids" | grep -c .)" in
    0) return 0 ;;
    1) ;;
    *) echo "error: more than one app is named $1; rename or remove the extras" >&2; exit 1 ;;
  esac
  owned=$(az ad app owner list --id "$ids" --query "[?id=='$me'] | length(@)" -o tsv)
  if [ "$owned" = "0" ]; then
    echo "error: an app named $1 ($ids) exists but you don't own it; not reusing it" >&2
    exit 1
  fi
  echo "$ids"
}

sp_id_for() {  # the service principal's object id for an appId, created if missing
  local id
  id=$(az ad sp list --filter "appId eq '$1'" --query "[0].id" -o tsv)
  if [ -z "$id" ]; then
    id=$(az ad sp create --id "$1" --query id -o tsv)
  fi
  echo "$id"
}

read -r -p "Create or update $API_NAME and grant $ROLE_VALUE to: $*? Type yes to go ahead: " answer
[ "$answer" = "yes" ] || { echo "stopped; nothing was changed" >&2; exit 1; }

# --- The API app ---------------------------------------------------------------
api_app_id=$(app_id_for "$API_NAME")
if [ -z "$api_app_id" ]; then
  role_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
  roles=$(mktemp)
  trap 'rm -f "$roles"' EXIT
  cat > "$roles" <<JSON
[{"allowedMemberTypes": ["Application"], "description": "Request governance reviews from Patricia.",
  "displayName": "Request reviews", "isEnabled": true, "value": "$ROLE_VALUE", "id": "$role_id"}]
JSON
  api_app_id=$(az ad app create --display-name "$API_NAME" --sign-in-audience AzureADMyOrg \
    --app-roles "@$roles" --query appId -o tsv)
  echo "created $API_NAME ($api_app_id)" >&2
fi
# v2 access tokens carry azp and the v2 issuer the server is configured for.
az ad app update --id "$api_app_id" --identifier-uris "api://$api_app_id" \
  --set api.requestedAccessTokenVersion=2
api_sp=$(sp_id_for "$api_app_id")
# Only apps assigned a role can get a token for the API at all, before the server's own checks.
az ad sp update --id "$api_sp" --set appRoleAssignmentRequired=true
role_id=$(az ad app show --id "$api_app_id" --query "appRoles[?value=='$ROLE_VALUE'].id | [0]" -o tsv)
if [ -z "$role_id" ]; then
  echo "error: $API_NAME has no $ROLE_VALUE app role" >&2
  exit 1
fi

# --- One client app per caller --------------------------------------------------
clients=()
for caller in "$@"; do
  name="$caller-patricia-client"
  client_app_id=$(app_id_for "$name")
  if [ -z "$client_app_id" ]; then
    client_app_id=$(az ad app create --display-name "$name" --sign-in-audience AzureADMyOrg --query appId -o tsv)
    echo "created $name ($client_app_id)" >&2
  fi
  client_sp=$(sp_id_for "$client_app_id")
  granted=$(az rest --method GET \
    --url "https://graph.microsoft.com/v1.0/servicePrincipals/$client_sp/appRoleAssignments" \
    --query "value[?resourceId=='$api_sp' && appRoleId=='$role_id'] | length(@)" -o tsv)
  if [ "$granted" = "0" ]; then
    az rest --method POST \
      --url "https://graph.microsoft.com/v1.0/servicePrincipals/$api_sp/appRoleAssignedTo" \
      --body "{\"principalId\": \"$client_sp\", \"resourceId\": \"$api_sp\", \"appRoleId\": \"$role_id\"}" >/dev/null
    echo "granted $ROLE_VALUE to $name" >&2
  fi
  clients+=("$client_app_id")
done

# --- What main.bicep needs ------------------------------------------------------
printf '\nFor main.bicepparam:\n'
printf "  param apiAppId = '%s'\n" "$api_app_id"
printf "  param allowedClients = [%s]\n" "$(printf "'%s', " "${clients[@]}" | sed 's/, $//')"
printf '\nEach product requests a token with scope api://%s/.default\n' "$api_app_id"
