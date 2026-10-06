#!/usr/bin/env bash
# Validate the repo's portable artifacts. Used by CI and the Claude Code PostToolUse hook.
# Checks that every SKILL.md / AGENTS.md has YAML frontmatter with the required keys.
# Exit non-zero on any failure (the hook tolerates failures; CI does not).
set -uo pipefail

fail=0

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
  check_frontmatter "$f" name description
done < <(find hives -type f -name 'SKILL.md' -print0 2>/dev/null)

# AGENTS.md files are instruction docs; require a top-level heading, not frontmatter.
while IFS= read -r -d '' f; do
  if ! grep -qE '^#[[:space:]]' "$f"; then
    echo "FAIL  $f: AGENTS.md has no top-level heading"; fail=1
  fi
done < <(find hives -type f -name 'AGENTS.md' -print0 2>/dev/null)

if [ "$fail" -eq 0 ]; then
  echo "OK  all SKILL.md / AGENTS.md artifacts valid"
fi
exit "$fail"
