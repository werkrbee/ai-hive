#!/usr/bin/env bash
# Exercise assurance.sh against a stubbed az whose file share is a local directory. The
# hosted queue lists what the weekly evaluation found; an answer at a terminal goes back
# to the share with its audit entry, the key only ever in the environment; an answer
# without a terminal is refused and nothing is uploaded; and when the share's audit log
# changes while a person answers, nothing is uploaded. A template from before the weekly
# job has nothing to read. Bash 3.2 safe; run it with /bin/bash on macOS.
#
# Usage: tests/assurance_test.sh        (from hives/agents-hive/deploy/azure, or anywhere)
set -u

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../../../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0
export STUB="$work/stub"

# The stub. $STUB/share is the file share; $STUB/outputs the last deployment's outputs.
# Every call is appended to $STUB/calls. Once $STUB/race exists, the share's audit log
# gains a line the first time its etag is read after that.
mkdir -p "$work/bin"
cat > "$work/bin/az" <<'STUB'
#!/usr/bin/env bash
args="$*"
echo "$args" >> "$STUB/calls"
echo "${AZURE_STORAGE_KEY:-}" >> "$STUB/keys"
arg() { printf '%s' "$args" | sed -n "s/.*$1 \([^ ]*\).*/\1/p"; }
case "$args" in
  "deployment group show"*) cat "$STUB/outputs" ;;
  "storage account keys list"*) echo "s3cretkey" ;;
  "storage file download-batch"*)
    mkdir -p "$(arg --destination)" && cp -R "$STUB/share/assurance" "$(arg --destination)/" ;;
  "storage file show"*)
    log="$STUB/share/assurance/audit.jsonl"
    [ -f "$log" ] || exit 1
    if [ -f "$STUB/race" ] && [ ! -f "$STUB/raced" ]; then
      touch "$STUB/raced"
    elif [ -f "$STUB/raced" ] && [ ! -f "$STUB/raced2" ]; then
      touch "$STUB/raced2"; echo '{"seq": 99}' >> "$log"
    fi
    cksum < "$log" | cut -d' ' -f1 ;;
  "storage file upload-batch"*)
    cp -R "$(arg --source)/." "$STUB/share/$(arg --destination-path)/" ;;
  "storage file upload"*)
    cp "$(arg --source)" "$STUB/share/$(arg --path)" ;;
esac
STUB
chmod +x "$work/bin/az"

# A share as the weekly job leaves it after it found drift: one open item and its audit
# entries.
setup() {
  rm -rf "$STUB" && mkdir -p "$STUB/share/assurance"
  : > "$STUB/calls"
  echo '{"dataAccount": {"value": "patriciasttest"}, "auditBlobUrl": {"value": "https://patricialogtest.blob.core.windows.net/audit/patricia.jsonl"}}' \
    > "$STUB/outputs"
  item=$(python3 - "$repo" "$STUB/share/assurance" <<'PY'
import importlib.util, sys
from pathlib import Path
repo, state = Path(sys.argv[1]), Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("engine", repo / "hives/workflows-hive/scripts/run.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
e = engine.Engine(state / "runs", queue=state / "queue", audit=state / "audit.jsonl", log=lambda *a: None)
agent = {"passport": "patricia", "version": 10, "sha256": "a" * 64}
e.append_audit({"kind": "eval.ran", "agent": agent, "result": "2026-11-02-patricia-weekly-eval"})
print(e.drift(agent, "2026-11-02-patricia-weekly-eval", {"summary": "met 15 of 17"}, "drift")["id"])
PY
)
}
# assurance ARGS... — run it with no terminal; in_terminal ARGS... — with one.
assurance() { out=$(PATH="$work/bin:$PATH" /bin/bash "$here/../assurance.sh" "$@" 2>&1 </dev/null); code=$?; }
# A pseudo-terminal for the command's stdin and stdout, as a person's would be; its output
# is copied out until it exits.
cat > "$work/tty.py" <<'PY'
import os, subprocess, sys
leader, follower = os.openpty()
child = subprocess.Popen(sys.argv[1:], stdin=follower, stdout=follower, stderr=follower)
os.close(follower)
while True:
    try:
        data = os.read(leader, 4096)
    except OSError:
        break
    if not data:
        break
    sys.stdout.buffer.write(data)
sys.exit(child.wait())
PY
in_terminal() {
  out=$(PATH="$work/bin:$PATH" WORKFLOWS_HIVE_ACTOR=usr_test python3 "$work/tty.py" \
    /bin/bash "$here/../assurance.sh" "$@" 2>&1 </dev/null)
  code=$?
}
check() {  # LABEL CONDITION...
  local label="$1"; shift
  if "$@"; then echo "pass  $label"; else echo "FAIL  $label"; printf '%s\n' "$out" | sed 's/^/      /'; fail=1; fi
}
has() { printf '%s\n' "$out" | grep -q -- "$1"; }
status() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["status"])' \
  "$STUB/share/assurance/queue/${item#sha256:}.json"; }

setup
assurance list rg-test
check "list: shows the drift the weekly evaluation found" \
  eval '[ "$code" -eq 0 ] && has "${item:7:12}" && has drift'

setup
in_terminal approve rg-test "$item"
check "approve at a terminal: the item and its audit entry go back to the share" \
  eval '[ "$code" -eq 0 ] && [ "$(status)" = answered ] \
   && grep -q "\"kind\": \"drift.answered\"" "$STUB/share/assurance/audit.jsonl" \
   && python3 "$repo/hives/knowledge-hive/scripts/check_audit.py" "$STUB/share/assurance/audit.jsonl" >/dev/null \
   && has "pushes the audit entry to its immutable copy when it next runs"'
check "approve: the account key is only ever in the environment" \
  eval 'grep -q s3cretkey "$STUB/keys" && ! grep -q s3cretkey "$STUB/calls"'

setup
assurance approve rg-test "$item" --by usr_test
check "approve without a terminal: refused, and nothing is uploaded" \
  eval '[ "$code" -ne 0 ] && has "refusing to answer without an interactive terminal" \
   && [ "$(status)" = open ] && ! grep -q "^storage file upload" "$STUB/calls"'

setup
touch "$STUB/race"
in_terminal deny rg-test "$item" --reason "the provider changed the model"
check "deny while the job writes the log: nothing is uploaded" \
  eval '[ "$code" -ne 0 ] && has "the share.s audit log changed while you answered" \
   && [ "$(status)" = open ] && ! grep -q "^storage file upload" "$STUB/calls"'

setup
echo '{"registry": {"value": "reg.azurecr.io"}}' > "$STUB/outputs"
assurance list rg-test
check "a template from before the weekly job: nothing to read" \
  eval '[ "$code" -ne 0 ] && has "predates the weekly evaluation" && ! grep -q "^storage" "$STUB/calls"'

[ "$fail" -eq 0 ] && echo "OK  assurance.sh checks passed"
exit "$fail"
