#!/usr/bin/env bash
# Check deployed hosted Barry end to end: his Agent Card is served, a call without a token
# is refused, and a goal with a gated action pauses for a person and completes once
# approved. The gated action is the verify MCP server's record_note (servers/verify-mcp),
# which keeps a note in memory; Patricia reviews it before it pauses, as for any caller.
#
# The goal is sent as the verify caller (entra.sh --agent barry verify), which needs a
# credential for one token. So, once you type yes, this adds a client secret to
# verify-barry-client that expires within the hour, uses it for one token, and deletes it
# on the way out, whatever happens. The secret and the token stay in this process's
# environment; neither is printed or written to disk. You approve the gated call as --by
# (or WORKFLOWS_HIVE_ACTOR), an opaque actor id, never a name or email.
#
# It costs one short run of Barry's model and one of Patricia's reviews, a few cents.
#
# Usage: ./verify_barry.sh [--by ACTOR-ID] <resource-group>
# Needs: az login, as an owner of verify-barry-client; Barry's managed identity granted
# Patricia's and the verify server's roles (entra.sh --identity).
set -euo pipefail

by=${WORKFLOWS_HIVE_ACTOR:-}
if [ "${1:-}" = "--by" ]; then
  [ "$#" -ge 2 ] || { echo "usage: $0 [--by ACTOR-ID] <resource-group>" >&2; exit 2; }
  by=$2; shift 2
fi
if [ "$#" -ne 1 ] || [ -z "$by" ]; then
  echo "usage: $0 [--by ACTOR-ID] <resource-group>   (or set WORKFLOWS_HIVE_ACTOR)" >&2
  exit 2
fi
rg=$1

outputs=$(az deployment group show --resource-group "$rg" --name main --query properties.outputs -o json)
output() {
  python3 -c 'import json, sys; print((json.loads(sys.argv[1]).get(sys.argv[2]) or {}).get("value", ""))' \
    "$outputs" "$1"
}
barry=$(output barryUrl)
if [ -z "$barry" ]; then
  echo "error: the deployment in $rg has no hosted Barry (barry isn't set in its parameters)" >&2
  exit 1
fi
tenant=$(az account show --query tenantId -o tsv)
api=$(az ad app list --filter "displayName eq 'barry-a2a-api'" --query "[0].appId" -o tsv)
client=$(az ad app list --filter "displayName eq 'verify-barry-client'" --query "[0].appId" -o tsv)
if [ -z "$api" ] || [ -z "$client" ]; then
  echo "error: barry-a2a-api or verify-barry-client is missing; run entra.sh --agent barry verify" >&2
  exit 1
fi

echo "== the card and an unauthenticated call"
python3 - "$barry" <<'PY'
import json, sys, urllib.error, urllib.request
barry = sys.argv[1]
with urllib.request.urlopen(barry + ".well-known/agent-card.json", timeout=60) as r:
    card = json.load(r)
print(f"card: {card['name']}, {len(card.get('skills', []))} skill(s)")
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "none"}}).encode()
req = urllib.request.Request(barry, data=body, headers={"content-type": "application/json", "A2A-Version": "1.0"})
try:
    urllib.request.urlopen(req, timeout=60)
except urllib.error.HTTPError as e:
    if e.code != 401:
        sys.exit(f"error: a call without a token got HTTP {e.code}, not 401")
    print("a call without a token: refused, 401")
else:
    sys.exit("error: a call without a token was answered")
PY

read -r -p "Add a client secret, expiring within the hour, to verify-barry-client ($client), use it for one token, then delete it? Type yes to go ahead: " answer
[ "$answer" = "yes" ] || { echo "stopped; nothing was changed" >&2; exit 1; }

label="verify-barry-$(date -u +%Y%m%dT%H%M%SZ)"
end=$(python3 -c 'import datetime; print((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))')
cleanup() {
  local key
  key=$(az ad app credential list --id "$client" --query "[?displayName=='$label'].keyId | [0]" -o tsv 2>/dev/null || true)
  if [ -n "$key" ]; then
    if az ad app credential delete --id "$client" --key-id "$key" 2>/dev/null; then
      echo "deleted the client secret $label"
    else
      echo "error: couldn't delete the client secret $label from $client; delete it: az ad app credential delete --id $client --key-id $key" >&2
    fi
  fi
}
trap cleanup EXIT
VERIFY_SECRET=$(az ad app credential reset --id "$client" --append --display-name "$label" --end-date "$end" \
  --query password -o tsv 2>/dev/null)
export VERIFY_SECRET

echo "== a gated goal: pause, approve, complete"
python3 - "$barry" "$tenant" "$client" "$api" "$by" <<'PY'
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
barry, tenant, client, api, by = sys.argv[1:]


def token():
    form = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": client,
                                   "client_secret": os.environ["VERIFY_SECRET"], "scope": f"api://{api}/.default"})
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    for attempt in range(8):  # a new secret takes a little while to be accepted
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=form.encode()), timeout=60) as r:
                return json.load(r)["access_token"]
        except urllib.error.HTTPError:
            time.sleep(10)
    sys.exit("error: couldn't get a token as verify-barry-client")


bearer = token()


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(barry, data=body, headers={"content-type": "application/json", "A2A-Version": "1.0",
                                                            "authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        reply = json.load(r)
    if "error" in reply:
        sys.exit(f"error: {method}: {reply['error'].get('message')}")
    return reply["result"]


def wait(task_id, states, minutes=10):
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        task = rpc("GetTask", {"id": task_id})
        if task["status"]["state"] in states:
            return task
        time.sleep(3)
    sys.exit(f"error: task {task_id} stayed {task['status']['state']} for {minutes} minutes")


def text(task):
    return " ".join(p.get("text", "") for p in task["status"].get("message", {}).get("parts", []))


note = f"Hosted Barry checked at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}."
goal = (f"Record this note on the verify server: \"{note}\" Report one result with workstream \"note\" and "
        "result \"recorded\" or \"not recorded\".")
ended = ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED")
message = {"messageId": f"verify-{time.time_ns()}", "role": "ROLE_USER", "parts": [{"data": {"goal": goal}}]}
task = rpc("SendMessage", {"message": message})["task"]
print(f"task {task['id']}: {task['status']['state']}")
task = wait(task["id"], ended + ("TASK_STATE_INPUT_REQUIRED",))
if task["status"]["state"] != "TASK_STATE_INPUT_REQUIRED":
    sys.exit(f"error: the task ended {task['status']['state']} without pausing: {text(task)}")
[request] = [p["data"]["approval"] for p in task["status"]["message"]["parts"] if "approval" in p.get("data", {})]
print(f"paused for {request['tool']} ({request['action']}), showing {json.dumps(request['present'])}; "
      f"Patricia: {request.get('review', {}).get('verdict')}")
if request["tool"] != "verify/record_note" or request["present"].get("note") != note:
    sys.exit("error: the approval isn't for the note the goal asked for; not approving it")
answer = {"messageId": f"verify-{time.time_ns()}", "role": "ROLE_USER", "taskId": task["id"],
          "contextId": task["contextId"],
          "parts": [{"data": {"approval": {"id": request["id"], "decision": "approve", "by": by}}}]}
rpc("SendMessage", {"message": answer})
task = wait(task["id"], ended)
if task["status"]["state"] != "TASK_STATE_COMPLETED":
    sys.exit(f"error: the approved task ended {task['status']['state']}: {text(task)}")
result = task["artifacts"][0]["parts"][0]["data"]
print(f"completed: {result['summary']}")
if not any(r.get("workstream") == "note" and r.get("result") == "recorded" for r in result.get("results", [])):
    sys.exit("error: the task completed but doesn't report the note as recorded")
print("OK  hosted Barry: card served, unauthenticated call refused, gated call paused and ran once approved")
PY
