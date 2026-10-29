#!/usr/bin/env bash
# Read and answer what Patricia's weekly trust evaluation recorded in Azure, and check her
# audit log against its immutable copy.
#
# The weekly job (eval/weekly.sh) keeps its results, its review queue and its audit log on
# the deployment's file share, under assurance/. Drift it found holds promotion: deploy.sh
# reads the queue before it deploys. This downloads assurance/ to a temporary directory
# and runs workflows-hive's review_queue.py on it, so an answer is given the way a local
# one is: by a person, at an interactive terminal, under their actor id (--by, or
# WORKFLOWS_HIVE_ACTOR), recorded in the audit log with via "cli". The answered item and
# the audit log then go back to the share, unless the share's log changed while you
# answered (the job ran, say), in which case nothing is uploaded and you answer again. The
# job pushes the new audit entries to the immutable copy when it next runs.
#
# Usage:
#   ./assurance.sh list    <resource-group> [--all]
#   ./assurance.sh show    <resource-group> ID
#   ./assurance.sh approve <resource-group> ID [--by ACTOR-ID]
#   ./assurance.sh deny    <resource-group> ID --reason TEXT [--by ACTOR-ID]
#   ./assurance.sh check   <resource-group>    # the audit log against its immutable copy
# Needs: az login, as someone who can read the data account's key; check also needs
# Storage Blob Data Reader on the audit container (main.bicep's auditReaders).
set -euo pipefail

usage() {
  sed -n 's/^#   \(\.\/assurance\.sh .*\)/  \1/p' "$0" >&2
  exit 2
}
[ "$#" -ge 2 ] || usage
command=$1 rg=$2
shift 2
case "$command" in list|show|approve|deny|check) ;; *) usage ;; esac

here=$(cd "$(dirname "$0")" && pwd)
root=$(git -C "$here" rev-parse --show-toplevel)
queue_py=$root/hives/workflows-hive/scripts/review_queue.py
share=hive-a2a-data

outputs=$(az deployment group show --resource-group "$rg" --name main --query properties.outputs -o json) || {
  echo "error: couldn't read the deployment in $rg" >&2
  exit 1
}
value() { python3 -c 'import json, sys; print((json.loads(sys.argv[1]).get(sys.argv[2]) or {}).get("value", ""))' "$outputs" "$1"; }
account=$(value dataAccount) blob=$(value auditBlobUrl)
if [ -z "$account" ]; then
  echo "error: the template deployed in $rg predates the weekly evaluation; there is nothing to read" >&2
  exit 1
fi
# The share takes the account key; it goes in the environment, never an argument.
AZURE_STORAGE_KEY=$(az storage account keys list --resource-group "$rg" --account-name "$account" \
  --query '[0].value' -o tsv)
export AZURE_STORAGE_KEY

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
state=$work/assurance
queue() { python3 "$queue_py" --state-dir "$state/runs" --queue-dir "$state/queue" --audit "$state/audit.jsonl" "$@"; }

# The share's audit log's etag, or "none" before the job has written one.
etag() {
  az storage file show --account-name "$account" --share-name "$share" --path assurance/audit.jsonl \
    --query properties.etag -o tsv 2>/dev/null || echo none
}

# An answer's etag is read before the download, so a log the job wrote at any point after
# it, during the download included, stops the upload rather than being overwritten.
case "$command" in approve|deny) before=$(etag) ;; esac
az storage file download-batch --account-name "$account" --source "$share" --pattern 'assurance/*' \
  --destination "$work" -o none
mkdir -p "$state/queue" "$state/runs"

case "$command" in
  list|show)
    queue "$command" "$@" ;;
  approve|deny)
    queue "$command" "$@"
    if [ "$(etag)" != "$before" ]; then
      echo "error: the share's audit log changed while you answered (the weekly job may be running);" \
        "nothing was uploaded, so answer again once it is done" >&2
      exit 1
    fi
    # The audit entry first: an answer the log records but the queue doesn't show is safer
    # than the other way round.
    az storage file upload --account-name "$account" --share-name "$share" \
      --source "$state/audit.jsonl" --path assurance/audit.jsonl -o none
    az storage file upload-batch --account-name "$account" --destination "$share" \
      --destination-path assurance/queue --source "$state/queue" -o none
    echo "answered on the share; the weekly job pushes the audit entry to its immutable copy when it next runs" ;;
  check)
    python3 "$here/audit_blob.py" check "$state/audit.jsonl" "$blob" ;;
esac
