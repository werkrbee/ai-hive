#!/usr/bin/env bash
# Exercise verify_barry.sh against a stubbed az and a local stand-in for hosted Barry's A2A
# endpoint and the token endpoint, on 127.0.0.1. Declining the secret changes nothing; the
# secret is deleted however the script exits, on success, failure or an interrupt; a typed
# yes approves as --by, and any other answer, or a request for a different note, is denied
# with a reason; a task that ends without pausing, or never completes, fails and names its
# state. The answers come from files: the first on standard input, the second through
# VERIFY_BARRY_TTY, which, like VERIFY_BARRY_LOGIN, is refused when what it would reach
# isn't on this machine. Nothing leaves the machine: the script's Python can reach only
# loopback addresses, and its sleeps only move a clock forward. Bash 3.2 safe; run it with
# /bin/bash on macOS.
#
# Usage: tests/verify_barry_test.sh        (from hives/agents-hive/deploy/azure, or anywhere)
set -u

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
server=
trap '[ -z "$server" ] || { kill "$server"; wait "$server"; } 2>/dev/null; rm -rf "$work"' EXIT
fail=0
export STUB="$work/stub"

# The stub. Every call is appended to $STUB/calls; a call it doesn't know is recorded as
# unexpected and fails, so none can fall through to a real az. $STUB/creds holds the label of
# the client secret while it exists; $STUB/barry, when it exists, is Barry's URL in place of
# the stand-in's.
mkdir -p "$work/bin" "$work/py"
cat > "$work/bin/az" <<'STUB'
#!/usr/bin/env bash
args="$*"
echo "$args" >> "$STUB/calls"
arg() { printf '%s' "$args" | sed -n "s/.*$1 \([^ ]*\).*/\1/p"; }
case "$args" in
  "deployment group show"*)
    if [ -f "$STUB/barry" ]; then url=$(cat "$STUB/barry"); else url="http://127.0.0.1:$(cat "$STUB/port")/"; fi
    printf '{"barryUrl": {"value": "%s"}}\n' "$url" ;;
  "account show"*) echo "tenant-1" ;;
  "ad app list --filter displayName eq 'barry-a2a-api'"*) echo "api-app" ;;
  "ad app list --filter displayName eq 'verify-barry-client'"*) echo "client-app" ;;
  "ad app credential reset --id client-app --append --display-name "*" --end-date "*)
    arg --display-name > "$STUB/creds"; echo "s3cret-pw" ;;
  "ad app credential list --id client-app"*)
    if [ -s "$STUB/creds" ] && printf '%s' "$args" | grep -q "displayName=='$(cat "$STUB/creds")'"; then echo "key-1"; fi ;;
  "ad app credential delete --id client-app --key-id key-1") : > "$STUB/creds" ;;
  *) echo "unexpected: $args" >> "$STUB/calls"; exit 97 ;;
esac
STUB
chmod +x "$work/bin/az"

# Loaded by the script's Python through PYTHONPATH: a host other than loopback is refused
# before any lookup or connection, and time.sleep moves time.monotonic forward instead of
# waiting, so the ten-minute wait and the token retries run in moments.
cat > "$work/py/sitecustomize.py" <<'PY'
import socket, time
_local = ("127.0.0.1", "localhost", "::1")
_getaddrinfo, _connect, _connect_ex = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex


def _check(host):
    if host not in _local:
        raise OSError(f"test: no network, refused {host}")


def getaddrinfo(host, *args, **kwargs):
    _check(host)
    return _getaddrinfo(host, *args, **kwargs)


def connect(self, address):
    if isinstance(address, tuple):
        _check(address[0])
    return _connect(self, address)


def connect_ex(self, address):
    if isinstance(address, tuple):
        _check(address[0])
    return _connect_ex(self, address)


socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = getaddrinfo, connect, connect_ex
_monotonic, _skew = time.monotonic, [0.0]
time.sleep = lambda seconds: _skew.__setitem__(0, _skew[0] + seconds)
time.monotonic = lambda: _monotonic() + _skew[0]
PY

# The stand-in for Barry and the token endpoint, on an ephemeral port written to
# $STUB/port. $STUB/mode says how the task goes once sent: pause (for the note it was
# asked), wrong-note, no-pause, never (stays working) or hang (GetTask doesn't answer).
# Token requests go to $STUB/tokens and approval decisions to $STUB/decisions.
cat > "$work/standin.py" <<'PY'
import json, os, sys, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
stub = sys.argv[1]
mode = open(os.path.join(stub, "mode")).read().strip()
task = {}


def log(name, entry):
    with open(os.path.join(stub, name), "a") as f:
        f.write(json.dumps(entry) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/.well-known/agent-card.json":
            return self.reply(200, {"name": "barry", "skills": [{"id": "orchestrate"}]})
        self.reply(404, {})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path == "/login/tenant-1/oauth2/v2.0/token":
            form = dict(urllib.parse.parse_qsl(body.decode()))
            log("tokens", form)
            good = form == {"grant_type": "client_credentials", "client_id": "client-app",
                            "client_secret": "s3cret-pw", "scope": "api://api-app/.default"}
            return self.reply(200, {"access_token": "tok-1"}) if good else self.reply(401, {})
        if self.path != "/" or self.headers.get("authorization") != "Bearer tok-1":
            return self.reply(401, {})
        call = json.loads(body)
        self.reply(200, {"jsonrpc": "2.0", "id": call["id"], "result": self.rpc(call["method"], call["params"])})

    def rpc(self, method, params):
        if method == "SendMessage" and "taskId" not in params["message"]:
            goal = params["message"]["parts"][0]["data"]["goal"]
            note = goal.split('"')[1] if mode != "wrong-note" else "Something else entirely."
            task.update(id="task-1", contextId="ctx-1", status={"state": "TASK_STATE_WORKING"}, note=note)
            return {"task": self.view()}
        if method == "SendMessage":
            approval = params["message"]["parts"][0]["data"]["approval"]
            log("decisions", approval)
            if approval["decision"] == "approve":
                task["status"] = {"state": "TASK_STATE_COMPLETED"}
                task["artifacts"] = [{"parts": [{"data": {"summary": "recorded the note",
                                                          "results": [{"workstream": "note", "result": "recorded"}]}}]}]
            else:
                task["status"] = {"state": "TASK_STATE_REJECTED"}
            return {"task": self.view()}
        if task["status"]["state"] == "TASK_STATE_WORKING" and mode != "never":
            if mode == "hang":
                open(os.path.join(stub, "hanging"), "w").close()
                time.sleep(60)
            elif mode == "no-pause":
                task["status"] = {"state": "TASK_STATE_COMPLETED",
                                  "message": {"parts": [{"text": "finished without asking"}]}}
            else:
                approval = {"id": "approval-1", "tool": "verify/record_note", "action": "record_note",
                            "present": {"note": task["note"]}, "review": {"verdict": "pass", "reason": "a note"}}
                task["status"] = {"state": "TASK_STATE_INPUT_REQUIRED",
                                  "message": {"parts": [{"data": {"approval": approval}}]}}
        return self.view()

    def view(self):
        return {k: v for k, v in task.items() if k != "note"}


httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
with open(os.path.join(stub, "port.tmp"), "w") as f:
    f.write(str(httpd.server_address[1]))
os.rename(os.path.join(stub, "port.tmp"), os.path.join(stub, "port"))
httpd.serve_forever()
PY

# Run the script in its own session and interrupt it, as Ctrl-C would its process group,
# once the stand-in is holding its GetTask. It runs isolated (-I), on the real clock; the
# script it starts still gets the guard and the fake clock.
cat > "$work/interrupt.py" <<'PY'
import os, signal, subprocess, sys, time
stub = os.environ["STUB"]
with open(sys.argv[1]) as stdin:
    child = subprocess.Popen(sys.argv[2:], stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             start_new_session=True)
deadline = time.monotonic() + 30
while not os.path.exists(os.path.join(stub, "hanging")) and child.poll() is None and time.monotonic() < deadline:
    time.sleep(0.05)
if child.poll() is None:
    os.killpg(child.pid, signal.SIGINT)
out, _ = child.communicate(timeout=30)
sys.stdout.buffer.write(out)
sys.exit(child.returncode)
PY

setup() {  # MODE
  [ -z "$server" ] || { kill "$server" 2>/dev/null; wait "$server" 2>/dev/null; }
  rm -rf "$STUB" && mkdir -p "$STUB"
  : > "$STUB/calls"; : > "$STUB/creds"; : > "$STUB/tokens"; : > "$STUB/decisions"
  echo "$1" > "$STUB/mode"
  python3 "$work/standin.py" "$STUB" &
  server=$!
  local i=0
  while [ ! -f "$STUB/port" ] && [ "$i" -lt 100 ]; do sleep 0.1; i=$((i + 1)); done
}
# The script's environment: only the stub's az first on PATH, no proxies, the network guard
# and fake clock, the stand-in's token URL (or login's, or none when it's set empty) and the
# answer file (or none when tty is set empty).
script_env() {
  local url="${login-http://127.0.0.1:$(cat "$STUB/port")/login}" answer="${tty-$STUB/answer}"
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u ALL_PROXY \
    -u VERIFY_BARRY_LOGIN -u VERIFY_BARRY_TTY no_proxy='*' \
    PATH="$work/bin:$PATH" PYTHONPATH="$work/py" PYTHONDONTWRITEBYTECODE=1 \
    ${url:+VERIFY_BARRY_LOGIN=$url} ${answer:+VERIFY_BARRY_TTY=$answer} WORKFLOWS_HIVE_ACTOR="${actor-}" "$@"
}
# verify FIRST-ANSWER SECOND-ANSWER ARGS... — the first answer is the script's standard
# input; the second is the file VERIFY_BARRY_TTY names.
verify() {
  printf '%s\n' "$1" > "$STUB/stdin"; printf '%s\n' "$2" > "$STUB/answer"; shift 2
  out=$(script_env /bin/bash "$here/../verify_barry.sh" "$@" 2>&1 < "$STUB/stdin"); code=$?
}
interrupted() {  # ARGS...
  printf 'yes\n' > "$STUB/stdin"; printf 'yes\n' > "$STUB/answer"
  out=$(script_env python3 -I "$work/interrupt.py" "$STUB/stdin" /bin/bash "$here/../verify_barry.sh" "$@" 2>&1); code=$?
}
check() {  # LABEL CONDITION...
  local label="$1"; shift
  if "$@"; then echo "pass  $label"; else echo "FAIL  $label"; printf '%s\n' "$out" | sed 's/^/      /'; fail=1; fi
}
has() { printf '%s\n' "$out" | grep -q -- "$1"; }
# The secret was made, then deleted by the label it was made with, and never shown or passed
# as an argument; and az saw nothing it doesn't know.
deleted() {
  grep -q "^ad app credential reset --id client-app --append --display-name verify-barry-" "$STUB/calls" \
    && grep -q "^ad app credential delete --id client-app --key-id key-1$" "$STUB/calls" \
    && [ ! -s "$STUB/creds" ] && has "deleted the client secret verify-barry-" && known
}
known() { ! grep -q "^unexpected" "$STUB/calls" && ! grep -q s3cret-pw "$STUB/calls" && ! has s3cret-pw; }
decided() {  # DECISION [REASON] — exactly one decision, as usr_test, with that reason or none
  python3 - "$STUB/decisions" "$@" <<'PY'
import json, sys
lines = open(sys.argv[1]).read().splitlines()
want = {"id": "approval-1", "decision": sys.argv[2], "by": "usr_test"}
if len(sys.argv) > 3:
    want["reason"] = sys.argv[3]
sys.exit(0 if [json.loads(l) for l in lines] == [want] else 1)
PY
}

setup pause
verify no yes --by usr_test rg-test
check "declining the secret: nothing is changed and no token is asked for" \
  eval '[ "$code" -ne 0 ] && has "refused, 401" && has "stopped; nothing was changed" \
   && ! grep -q credential "$STUB/calls" && [ ! -s "$STUB/tokens" ] && [ ! -s "$STUB/decisions" ] && known'

setup pause
verify yes yes --by usr_test rg-test
check "a typed yes: approved as --by, completed, and the secret deleted" \
  eval '[ "$code" -eq 0 ] && has "OK  hosted Barry" && has "Approve this call as usr_test?" \
   && has "the approval answer is read from .*/answer, not a terminal (a test)" && decided approve && deleted'

setup pause
actor=usr_test verify yes yes rg-test
check "a typed yes with WORKFLOWS_HIVE_ACTOR and no --by: approved as the actor" \
  eval '[ "$code" -eq 0 ] && decided approve && deleted'

setup pause
verify yes y --by usr_test rg-test
check "any other answer: denied with a reason, and the secret deleted" \
  eval '[ "$code" -ne 0 ] && has "denied the call, so nothing was recorded" \
   && decided deny "not approved at the check" && deleted'

setup pause
verify yes "" --by usr_test rg-test
check "no answer: denied with a reason" \
  eval '[ "$code" -ne 0 ] && decided deny "not approved at the check" && deleted'

setup wrong-note
verify yes yes --by usr_test rg-test
check "an approval for a different note: denied with a reason, whatever was typed" \
  eval '[ "$code" -ne 0 ] && has "isn.t for the note the goal asked for" && ! has "Approve this call" \
   && decided deny "not the note the check asked for" && deleted'

setup no-pause
verify yes yes --by usr_test rg-test
check "a task that ends without pausing: fails with its state, and the secret deleted" \
  eval '[ "$code" -ne 0 ] && has "ended TASK_STATE_COMPLETED without pausing: finished without asking" \
   && [ ! -s "$STUB/decisions" ] && deleted'

setup never
verify yes yes --by usr_test rg-test
check "a task that never completes: fails with its state, and the secret deleted" \
  eval '[ "$code" -ne 0 ] && has "stayed TASK_STATE_WORKING for 10 minutes" \
   && [ ! -s "$STUB/decisions" ] && deleted'

setup hang
interrupted --by usr_test rg-test
check "an interrupt while waiting on Barry: the secret deleted" \
  eval '[ "$code" -ne 0 ] && [ -f "$STUB/hanging" ] && [ ! -s "$STUB/decisions" ] && deleted'

# Without the stand-in's token URL the script asks Microsoft's; the guard refuses it before
# any lookup, so a test that forgot the seam fails here rather than reaching the network.
setup pause
login= tty= verify yes yes --by usr_test rg-test
check "the real token endpoint is out of reach: refused, and the secret deleted" \
  eval '[ "$code" -ne 0 ] && has "no network, refused login.microsoftonline.com" && [ ! -s "$STUB/tokens" ] && deleted'

# The seams talk only to this machine: each is refused, before anything is fetched or any
# secret made, when what it would reach is elsewhere.
for url in https://login.example.com http://localhost:1@login.example.com http://127.0.0.1.example.com; do
  setup pause
  login=$url verify yes yes --by usr_test rg-test
  check "VERIFY_BARRY_LOGIN=$url: refused before any secret" \
    eval '[ "$code" -eq 2 ] && has "VERIFY_BARRY_LOGIN is for the test.s stand-in, on this machine; refusing" \
     && ! grep -q "^ad app\|^account" "$STUB/calls" && known'
done

setup pause
echo "https://barry.example.com/" > "$STUB/barry"
verify yes yes --by usr_test rg-test
check "VERIFY_BARRY_TTY against a Barry elsewhere: refused before anything is fetched" \
  eval '[ "$code" -eq 2 ] && has "VERIFY_BARRY_TTY is for the test" && ! has "card:" \
   && ! grep -q credential "$STUB/calls" && known'

setup pause
login= verify yes yes --by usr_test rg-test
check "VERIFY_BARRY_TTY without the stand-in's token URL: refused before anything is fetched" \
  eval '[ "$code" -eq 2 ] && has "VERIFY_BARRY_TTY is for the test" && ! has "card:" \
   && ! grep -q credential "$STUB/calls" && known'

[ "$fail" -eq 0 ] && echo "OK  verify_barry.sh checks passed"
exit "$fail"
