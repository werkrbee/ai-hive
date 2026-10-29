#!/bin/sh
# Patricia's weekly trust evaluation, as the Container Apps job in main.bicep runs it: on
# its cron schedule, in the app's environment, under her managed identity, from the image
# the app runs, so it evaluates exactly what is deployed. No credential goes into CI.
#
# Everything it records stays on the share, under ASSURANCE_DIR: the evaluation in
# results.jsonl (ids <date>-patricia-weekly-eval, so they never match one in the repo),
# its findings in queue/ and its entries in audit.jsonl. Each call is metered into the
# job's own ledger, which the app counts toward the same ceiling (render_config.py). The
# audit log is pushed to its immutable append blob (AUDIT_BLOB_URL) before the evaluation,
# for anything an earlier run or a person's answer left unpushed, and again after it.
# deploy.sh reads results.jsonl and queue/ before it promotes a change, and assurance.sh
# answers what the queue holds.
#
# It exits as the evaluation does, 1 when it found drift or couldn't run, so a failed
# execution shows in the job's history; and 1 when the audit log can't be pushed, which
# means the log no longer starts with its immutable copy, or the blob can't be reached.
set -u
state=${ASSURANCE_DIR:-/data/assurance}
azure=/app/hives/agents-hive/deploy/azure
: "${AUDIT_BLOB_URL:?the job needs AUDIT_BLOB_URL, the append blob that keeps its audit log}"

mkdir -p "$state/runs" || exit 1
python /usr/local/bin/render_config.py /tmp/config.toml || exit 1
python "$azure/audit_blob.py" push "$state/audit.jsonl" "$AUDIT_BLOB_URL" || exit 1

cd /app/hives/agents-hive/servers/a2a || exit 1
python "$azure/eval/run.py" --passport patricia --config /tmp/config.toml --spacing 12 \
  --label weekly-eval --results "$state/results.jsonl" --state-dir "$state/runs" \
  --queue-dir "$state/queue" --audit "$state/audit.jsonl"
status=$?

python "$azure/audit_blob.py" push "$state/audit.jsonl" "$AUDIT_BLOB_URL" || exit 1
exit "$status"
