#!/usr/bin/env bash
# Open, or update, the one issue that lists prices falling due within a week. It changes
# nothing in the repo: each price is re-read and recorded in a reviewed PR
# (CONTRIBUTING.md, "Harness rows").
set -euo pipefail
title="Prices due for re-verification"
milestone="${PRICE_DUE_MILESTONE:?PRICE_DUE_MILESTONE names the milestone the issue goes in}"
within="${PRICE_DUE_WITHIN:-7}"
export GH_REPO="${GH_REPO:?GH_REPO must identify the repository}"
export GH_TOKEN="${GH_TOKEN:?GH_TOKEN must be supplied by GitHub Actions}"
entries="$(python3 -B scripts/harnesses.py due --within "$within")"
existing="$(gh issue list --state open --search "in:title \"$title\"" --json number,title \
  --jq "map(select(.title == \"$title\")) | .[0].number // empty")"
if [[ -z "$entries" ]]; then
  echo "Nothing falls due within $within days"
  [[ -n "$existing" ]] && echo "Left open for a maintainer to close once its prices are recorded: #$existing"
  exit 0
fi
# The body names no issue numbers, so it closes nothing.
intro="These prices in \`harnesses.json\` fall due within $within days, or already have. From each date, \`python3 scripts/harnesses.py check\` fails, and so does CI."
outro="For each one, read the page again, record what it says now with today's date (for an ended launch price, the new price, dropping \`until\` and \`then\`), and run \`python3 scripts/harnesses.py matrix\`, in a reviewed PR as CONTRIBUTING.md describes. This issue is opened and updated by \`.github/workflows/price-due.yml\`, which never changes the repo; close it once the prices are recorded."
body="$(printf '%s\n\n%s\n\n%s' "$intro" "$entries" "$outro")"
if [[ -n "$existing" ]]; then
  if [[ "$(gh issue view "$existing" --json body --jq .body)" == "$body" ]]; then
    echo "Issue #$existing is already current"
  else
    gh issue edit "$existing" --body "$body"
  fi
else
  gh issue create --title "$title" --milestone "$milestone" --body "$body"
fi
