#!/usr/bin/env bash
# Propose only the generated snapshot, based on main even during pre-merge CI.
set -euo pipefail
snapshot="docs/open-weight-models-monthly.json"
month="$(python3 -c 'import json; print(json.load(open("docs/open-weight-models-monthly.json"))["review_month_utc"])')"
[[ "$month" =~ ^[0-9]{4}-[0-9]{2}$ ]] || { echo "Invalid review month" >&2; exit 1; }
branch="automation/open-weight-models-$month"
export GH_REPO="${GH_REPO:?GH_REPO must identify the repository}"
export GH_TOKEN="${GH_TOKEN:?GH_TOKEN must be supplied by GitHub Actions}"
# The credential helper uses GH_TOKEN without putting its value in a URL or file.
gh auth setup-git
git fetch --no-tags origin main
base="$(git rev-parse FETCH_HEAD)"
workspace="$(mktemp -d)"
trap 'git worktree remove --force "$workspace/tree" >/dev/null 2>&1 || true; rm -rf "$workspace"' EXIT
cp "$snapshot" "$workspace/snapshot.json"
git worktree add --detach "$workspace/tree" "$base"
cd "$workspace/tree"
mkdir -p docs
cp "$workspace/snapshot.json" "$snapshot"
if git ls-files --error-unmatch "$snapshot" >/dev/null 2>&1 && git diff --quiet -- "$snapshot"; then
  echo "No metadata changes"
  exit 0
fi
# Never reuse or overwrite a branch that could contain human changes. Fail loud
# if a previous push did not create a PR, so a maintainer can recover it safely.
if git ls-remote --exit-code --heads origin "$branch" >/dev/null; then
  existing="$(gh pr list --head "$branch" --base main --state open --json url --jq '.[0].url // empty')"
  if [[ -n "$existing" ]]; then
    echo "Existing monthly review PR retained: $existing"
    exit 0
  fi
  echo "Monthly branch exists without an open review PR; refusing to overwrite: $branch" >&2
  exit 1
fi
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git switch -c "$branch"
git add -- "$snapshot"
git commit -m "docs: refresh monthly open-weight model metadata"
# Normal push rejects a concurrently created or changed branch.
git push origin "HEAD:refs/heads/$branch"
gh pr create --base main --head "$branch" --title "docs: monthly open-weight model license and download review" --body "Automated model-card metadata only. Do not merge without checking upstream licenses, release changes, and download access. Update the editorial guide manually."
