#!/usr/bin/env bash
# Create the Entra ID app registrations for a hosted agent: one API app that issues
# access tokens for its server, and one client app per calling product, each granted the
# API's app roles. Safe to re-run: existing apps are found by name and reused.
#
#   patricia  patricia-a2a-api, Review.Request (the default)
#   barry     barry-a2a-api, Orchestration.Request and Orchestration.Approve
#   verify    barry-verify-mcp-api, Verify.Call: the MCP server hosted Barry is checked
#             against (servers/verify-mcp)
#
# With --identity it instead grants the API's roles to a managed identity, by its
# principal (object) id: Barry's, for Patricia's API and the verify server's.
#
# It creates no secrets. Each product's owner adds a credential to their own app
# (preferably a certificate or a federated credential) and keeps it in that product's
# secret store.
#
# Usage: ./entra.sh [--agent patricia|barry|verify] <caller> [<caller> ...]
#        ./entra.sh --agent patricia|barry|verify --identity <principal-id>
#   e.g. ./entra.sh lineup singularity
#        ./entra.sh --agent barry verify
#        ./entra.sh --agent patricia --identity "$barry_principal"
# Needs: az login, with rights to create app registrations in the tenant (and, for
# --identity, to grant app roles). It reuses an existing app only when exactly one has
# that display name and you own it. It looks everything up first, prints what it will
# create, reuse and grant, and changes nothing until you type yes.
set -euo pipefail

usage() {
  echo "usage: $0 [--agent patricia|barry|verify] <caller> [<caller> ...]" >&2
  echo "       $0 --agent patricia|barry|verify --identity <principal-id>" >&2
  exit 2
}
agent=patricia identity=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --agent) [ "$#" -ge 2 ] || usage; agent=$2; shift 2 ;;
    --identity) [ "$#" -ge 2 ] || usage; identity=$2; shift 2 ;;
    -*) usage ;;
    *) break ;;
  esac
done
# Each role: its value, display name and description, separated by |.
case "$agent" in
  patricia) API_NAME="patricia-a2a-api"
    ROLES=("Review.Request|Request reviews|Request governance reviews from Patricia.") ;;
  barry) API_NAME="barry-a2a-api"
    ROLES=("Orchestration.Request|Request orchestration|Start and cancel tasks with hosted Barry."
           "Orchestration.Approve|Answer approvals|Approve or deny the gated actions hosted Barry asks about.") ;;
  verify) API_NAME="barry-verify-mcp-api"
    ROLES=("Verify.Call|Call the verify server|Call the MCP server hosted Barry is checked against.") ;;
  *) usage ;;
esac
VALUES=()
for r in "${ROLES[@]}"; do VALUES+=("${r%%|*}"); done
NAMES=$(printf '%s, ' "${VALUES[@]}" | sed 's/, $//')

if [ -n "$identity" ] && [ "$#" -gt 0 ]; then
  usage
fi
if [ -z "$identity" ] && [ "$#" -lt 1 ]; then
  usage
fi
if [ "$(printf '%s\n' "$@" | sort | uniq -d)" != "" ]; then
  echo "error: a caller is named more than once: $*" >&2
  exit 2
fi

me=$(az ad signed-in-user show --query id -o tsv)

# These helpers run inside $(...), where bash 3.2 (macOS) ignores set -e, so each az call
# exits explicitly on failure and the ownership check accepts only a positive answer.
app_id_for() {  # the appId of the one app with exactly this display name that you own, or nothing
  local ids owned
  ids=$(az ad app list --filter "displayName eq '$1'" --query "[].appId" -o tsv) || exit 1
  case "$(printf '%s' "$ids" | grep -c .)" in
    0) return 0 ;;
    1) ;;
    *) echo "error: more than one app is named $1; rename or remove the extras" >&2; exit 1 ;;
  esac
  owned=$(az ad app owner list --id "$ids" --query "[?id=='$me'] | length(@)" -o tsv) || exit 1
  if [ "$owned" != "1" ]; then
    echo "error: an app named $1 ($ids) exists but you don't own it; not reusing it." >&2
    echo "  If you created it, add yourself as owner and run this again:" >&2
    echo "  az ad app owner add --id $ids --owner-object-id $me" >&2
    exit 1
  fi
  echo "$ids"
}

sp_lookup() {  # the service principal's object id for an appId, or nothing
  local id
  id=$(az ad sp list --filter "appId eq '$1'" --query "[0].id" -o tsv) || exit 1
  echo "$id"
}

sp_id_for() {  # the service principal's object id for an appId, created if missing
  local id
  id=$(sp_lookup "$1") || exit 1
  if [ -z "$id" ]; then
    id=$(az ad sp create --id "$1" --query id -o tsv) || exit 1
  fi
  echo "$id"
}

add_owner() {  # make you an owner of a new app; Graph can take a moment to find it
  local try
  for try in 1 2 3; do
    az ad app owner add --id "$1" --owner-object-id "$me" && return 0
    sleep 5
  done
  echo "error: created $1 but couldn't make you its owner; run: az ad app owner add --id $1 --owner-object-id $me" >&2
  exit 1
}

role_id_for() {  # $1 = API appId, $2 = role value: the role's id, or nothing
  local id
  id=$(az ad app show --id "$1" --query "appRoles[?value=='$2'].id | [0]" -o tsv) || exit 1
  echo "$id"
}

missing_roles() {  # $1 = principal's sp id, $2 = API sp id, then role ids: the values not yet granted
  local sp=$1 api=$2 i=0 granted missing=()
  shift 2
  for role in "$@"; do
    granted=$(az rest --method GET \
      --url "https://graph.microsoft.com/v1.0/servicePrincipals/$sp/appRoleAssignments" \
      --query "value[?resourceId=='$api' && appRoleId=='$role'] | length(@)" -o tsv) || exit 1
    [ "$granted" != "0" ] || missing+=("${VALUES[$i]}")
    i=$((i + 1))
  done
  printf '%s, ' "${missing[@]+"${missing[@]}"}" | sed 's/, $//'
}

# --- Plan: look everything up and change nothing --------------------------------
plan_api=$(app_id_for "$API_NAME")
plan_api_sp=""
plan_roles=()
if [ -z "$plan_api" ]; then
  if [ -n "$identity" ]; then
    echo "error: $API_NAME doesn't exist yet; run $0 --agent $agent <caller>... first" >&2
    exit 1
  fi
  plural=''
  [ "${#VALUES[@]}" -eq 1 ] || plural=s
  plan="  $API_NAME: create, with the $NAMES app role$plural"
else
  for value in "${VALUES[@]}"; do
    role=$(role_id_for "$plan_api" "$value")
    if [ -z "$role" ]; then
      echo "error: $API_NAME ($plan_api) has no $value app role" >&2
      exit 1
    fi
    plan_roles+=("$role")
  done
  plan_api_sp=$(sp_lookup "$plan_api")
  plan="  $API_NAME: reuse $plan_api"
fi
plan="$plan
    set api://<appId>, v2 tokens and assignment required"
[ -n "$plan_api_sp" ] || plan="$plan; create its service principal"
grant_plan() {  # $1 = principal's sp id or nothing: what granting it the roles would do
  local missing
  if [ -z "$1" ] || [ -z "$plan_api_sp" ]; then
    echo "grant $NAMES"
    return
  fi
  missing=$(missing_roles "$1" "$plan_api_sp" "${plan_roles[@]}") || exit 1
  if [ -z "$missing" ]; then echo "already has $NAMES"; else echo "grant $missing"; fi
}
if [ -n "$identity" ]; then
  if [ -z "$plan_api_sp" ]; then
    echo "error: $API_NAME has no service principal yet; run $0 --agent $agent <caller>... first" >&2
    exit 1
  fi
  plan="$plan
  managed identity $identity: $(grant_plan "$identity")"
fi
for caller in "$@"; do
  name="$caller-$agent-client"
  id=$(app_id_for "$name")
  if [ -z "$id" ]; then
    plan="$plan
  $name: create; grant $NAMES"
    continue
  fi
  sp=$(sp_lookup "$id")
  grant=$(grant_plan "$sp") || exit 1
  [ -n "$sp" ] || grant="create its service principal; $grant"
  plan="$plan
  $name: reuse $id; $grant"
done

printf 'Plan:\n%s\n\n' "$plan" >&2
printf 'Type yes to go ahead: ' >&2
read -r answer || answer=""
[ "$answer" = "yes" ] || { echo "stopped; nothing was changed" >&2; exit 1; }

# --- The API app ---------------------------------------------------------------
api_app_id=$(app_id_for "$API_NAME")
if [ -z "$api_app_id" ]; then
  roles=$(mktemp)
  trap 'rm -f "$roles"' EXIT
  python3 - "${ROLES[@]}" > "$roles" <<'PY'
import json, sys, uuid
print(json.dumps([{"allowedMemberTypes": ["Application"], "description": d, "displayName": n,
                   "isEnabled": True, "value": v, "id": str(uuid.uuid4())}
                  for v, n, d in (r.split("|", 2) for r in sys.argv[1:])]))
PY
  api_app_id=$(az ad app create --display-name "$API_NAME" --sign-in-audience AzureADMyOrg \
    --app-roles "@$roles" --query appId -o tsv)
  # az ad app create doesn't make you an owner, and a re-run reuses only apps you own.
  add_owner "$api_app_id"
  echo "created $API_NAME ($api_app_id)" >&2
fi
# v2 access tokens carry azp and the v2 issuer the server is configured for. az ad app
# update can't set api.requestedAccessTokenVersion on an app whose api block is still
# empty, so that goes straight to Microsoft Graph.
az ad app update --id "$api_app_id" --identifier-uris "api://$api_app_id"
az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications(appId='$api_app_id')" \
  --body '{"api": {"requestedAccessTokenVersion": 2}}'
api_sp=$(sp_id_for "$api_app_id")
# Only apps assigned a role can get a token for the API at all, before the server's own checks.
az ad sp update --id "$api_sp" --set appRoleAssignmentRequired=true
role_ids=()
for value in "${VALUES[@]}"; do
  role_id=$(role_id_for "$api_app_id" "$value")
  if [ -z "$role_id" ]; then
    echo "error: $API_NAME has no $value app role" >&2
    exit 1
  fi
  role_ids+=("$role_id")
done

grant() {  # $1 = principal's sp id, $2 = its name: assign it each role it doesn't have
  local i=0 granted
  for role_id in "${role_ids[@]}"; do
    granted=$(az rest --method GET \
      --url "https://graph.microsoft.com/v1.0/servicePrincipals/$1/appRoleAssignments" \
      --query "value[?resourceId=='$api_sp' && appRoleId=='$role_id'] | length(@)" -o tsv)
    if [ "$granted" = "0" ]; then
      az rest --method POST \
        --url "https://graph.microsoft.com/v1.0/servicePrincipals/$api_sp/appRoleAssignedTo" \
        --body "{\"principalId\": \"$1\", \"resourceId\": \"$api_sp\", \"appRoleId\": \"$role_id\"}" >/dev/null
      echo "granted ${VALUES[$i]} to $2" >&2
    fi
    i=$((i + 1))
  done
}

if [ -n "$identity" ]; then
  grant "$identity" "managed identity $identity"
  exit 0
fi

# --- One client app per caller --------------------------------------------------
clients=()
for caller in "$@"; do
  name="$caller-$agent-client"
  client_app_id=$(app_id_for "$name")
  if [ -z "$client_app_id" ]; then
    client_app_id=$(az ad app create --display-name "$name" --sign-in-audience AzureADMyOrg --query appId -o tsv)
    add_owner "$client_app_id"
    echo "created $name ($client_app_id)" >&2
  fi
  client_sp=$(sp_id_for "$client_app_id")
  grant "$client_sp" "$name"
  clients+=("$client_app_id")
done

# --- What main.bicep needs ------------------------------------------------------
list=$(printf "'%s', " "${clients[@]}" | sed 's/, $//')
printf '\nFor main.bicepparam:\n'
case "$agent" in
  patricia)
    printf "  param apiAppId = '%s'\n" "$api_app_id"
    printf "  param allowedClients = [%s]\n" "$list" ;;
  *) printf "  in param %s: apiAppId: '%s', and these clients: [%s]\n" "$agent" "$api_app_id" "$list" ;;
esac
printf '\nEach product requests a token with scope api://%s/.default\n' "$api_app_id"
