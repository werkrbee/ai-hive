#!/usr/bin/env bash
# Validate the repo's portable artifacts. Used by CI and the Claude Code PostToolUse hook.
# Checks every SKILL.md for YAML frontmatter with the required keys and every AGENTS.md for
# a top-level heading. Fails if no SKILL.md is found at all (e.g. hives not checked out).
# Exit non-zero on any failure (the hook tolerates failures; CI does not).
set -uo pipefail

root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1

fail=0
skills=0
agents=0

check_frontmatter() {
  local file="$1"; shift
  local keys=("$@")
  # frontmatter must start on line 1 with '---'
  if [ "$(head -1 "$file")" != "---" ]; then
    echo "FAIL  $file: missing YAML frontmatter (no leading ---)"; fail=1; return
  fi
  local fm
  fm="$(awk 'NR==1{next} /^---[[:space:]]*$/{exit} {print}' "$file")"
  for key in "${keys[@]}"; do
    if ! printf '%s\n' "$fm" | grep -qE "^${key}:"; then
      echo "FAIL  $file: frontmatter missing '${key}'"; fail=1
    fi
  done
}

while IFS= read -r -d '' f; do
  skills=$((skills + 1))
  check_frontmatter "$f" name description
done < <(find . -path ./.git -prune -o -type f -name 'SKILL.md' -print0)

# AGENTS.md files are instruction docs; require a top-level heading, not frontmatter.
while IFS= read -r -d '' f; do
  agents=$((agents + 1))
  if ! grep -qE '^#[[:space:]]' "$f"; then
    echo "FAIL  $f: AGENTS.md has no top-level heading"; fail=1
  fi
done < <(find . -path ./.git -prune -o -type f -name 'AGENTS.md' -print0)

if [ "$skills" -eq 0 ]; then
  echo "FAIL  no SKILL.md found — are the hives checked out?"; fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "OK  ${skills} SKILL.md and ${agents} AGENTS.md artifacts valid"
fi
exit "$fail"
