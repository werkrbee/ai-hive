#!/usr/bin/env bash
# Open, or update, the one issue that lists the prices and capabilities falling due within
# a week. It changes nothing in the repo: each is re-read and recorded in a reviewed PR
# (CONTRIBUTING.md, "Harness rows").
set -euo pipefail
title="Prices and capabilities due for re-verification"
# The title before capabilities were listed; an issue still open under it is updated and
# retitled rather than duplicated.
old_title="Prices due for re-verification"
milestone="${PRICE_DUE_MILESTONE:?PRICE_DUE_MILESTONE names the milestone the issue goes in}"
within="${PRICE_DUE_WITHIN:-7}"
export GH_REPO="${GH_REPO:?GH_REPO must identify the repository}"
export GH_TOKEN="${GH_TOKEN:?GH_TOKEN must be supplied by GitHub Actions}"
entries="$(python3 -B scripts/harnesses.py due --within "$within")"
existing="$(gh issue list --state open --search "in:title \"due for re-verification\"" --json number,title \
  --jq "map(select(.title == \"$title\" or .title == \"$old_title\")) | .[0].number // empty")"
if [[ -z "$entries" ]]; then
  echo "Nothing falls due within $within days"
  [[ -n "$existing" ]] && echo "Left open for a maintainer to close once its dates are recorded: #$existing"
  exit 0
fi
# The body names no issue numbers, so it closes nothing.
intro="These prices and capabilities in \`harnesses.json\` fall due within $within days, or already have. From each date, \`python3 scripts/harnesses.py check\` fails, and so does CI."
outro="For each one, read the pages again, record what they say now with today's date (for an ended launch price, the new price, dropping \`until\` and \`then\`; for a capability that can't be confirmed, unknown), and run \`python3 scripts/harnesses.py matrix\`, in a reviewed PR as CONTRIBUTING.md describes. This issue is opened and updated by \`.github/workflows/price-due.yml\`, which never changes the repo; close it once the dates are recorded."
body="$(printf '%s\n\n%s\n\n%s' "$intro" "$entries" "$outro")"
if [[ -n "$existing" ]]; then
  current="$(gh issue view "$existing" --json title,body --jq '.title + "\n" + .body')"
  if [[ "$current" == "$title"$'\n'"$body" ]]; then
    echo "Issue #$existing is already current"
  else
    gh issue edit "$existing" --title "$title" --body "$body"
  fi
else
  gh issue create --title "$title" --milestone "$milestone" --body "$body"
fi
