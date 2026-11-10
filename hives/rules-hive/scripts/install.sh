#!/usr/bin/env bash
# Render a rules-hive ruleset into each harness's native instruction file.
#
# Rules/instructions are usually PROJECT-scoped, so the default target is the
# current directory. Use --dir to point at another project, or --global for the
# harnesses that support a user-level instruction file.
#
# Written for macOS's default Bash 3.2 — no associative arrays.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RULESET="queen-charter"
TARGET_DIR="."
GLOBAL=false
HARNESSES=""

HOUSE_ROOT="$(cd "${REPO_ROOT}/../.." && pwd)"
REGISTRY_PY="${HOUSE_ROOT}/scripts/harnesses.py"

# Instruction-file paths come from the House's registry (harnesses.json), read
# through scripts/harnesses.py. Many harnesses share the open AGENTS.md standard;
# the rest use their own filename. $1 is the scope (project, relative to the
# project dir, or global, the user-level file), $2 the harness; prints the path
# with the ruleset filled in, or nothing if the harness has none at that scope.
harness_rules_path() {
  python3 "$REGISTRY_PY" path rules "$1" "$2" --name "$RULESET" 2>/dev/null || true
}

usage() {
  cat <<'EOF'
Render a rules-hive ruleset into agent instruction files.

Options:
  --ruleset NAME    Ruleset under rules/ (default: queen-charter)
  --harness NAME    Target harness (repeatable); see the list below
  --dir PATH        Project directory to write into (default: current dir)
  --global          Write to the user-level file where supported
  -h, --help        Show this help

Default harnesses (if none given): agents claude-code cursor github-copilot gemini-cli

Harnesses with an instruction file (from harnesses.json):
EOF
  python3 "$REGISTRY_PY" list --surface rules | sed 's/^/  /'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ruleset) RULESET="$2"; shift 2 ;;
    --harness) HARNESSES="$HARNESSES $2"; shift 2 ;;
    --dir) TARGET_DIR="$2"; shift 2 ;;
    --global) GLOBAL=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if ! command -v python3 >/dev/null; then
  echo "python3 is needed to read the harness registry (${HOUSE_ROOT}/harnesses.json)" >&2
  exit 1
fi

SRC="${REPO_ROOT}/rules/${RULESET}/AGENTS.md"
if [ ! -f "$SRC" ]; then
  echo "ruleset not found: ${SRC}" >&2
  exit 1
fi

if [ -z "${HARNESSES// }" ]; then
  HARNESSES="agents claude-code cursor github-copilot gemini-cli"
fi

write_file() {
  # $1 = target path, $2 = harness (for cursor frontmatter)
  target="$1"; harness="$2"
  mkdir -p "$(dirname "$target")"
  if [ "$harness" = "cursor" ]; then
    {
      printf -- '---\ndescription: %s\nalwaysApply: true\n---\n\n' "$RULESET"
      cat "$SRC"
    } > "$target"
  else
    cat "$SRC" > "$target"
  fi
  echo "wrote: $target"
}

for harness in $HARNESSES; do
  if [ "$GLOBAL" = true ]; then
    gpath="$(harness_rules_path global "$harness")"
    if [ -z "$gpath" ]; then
      echo "skip: $harness has no user-level instruction file (use project scope)" >&2
      continue
    fi
    write_file "$gpath" "$harness"
  else
    rel="$(harness_rules_path project "$harness")"
    if [ -z "$rel" ]; then
      echo "unknown harness: $harness" >&2
      exit 1
    fi
    write_file "${TARGET_DIR%/}/$rel" "$harness"
  fi
done

echo "done."
