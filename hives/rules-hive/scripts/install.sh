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

# Per-harness PROJECT-relative instruction file. Many harnesses share the open
# AGENTS.md standard; the rest use their own filename.
harness_relpath() {
  case "$1" in
    agents|opencode|codex|kiro|databricks-genie-code|snowflake-cortex-code)
                    printf '%s' "AGENTS.md" ;;
    claude-code)    printf '%s' "CLAUDE.md" ;;
    cursor)         printf '%s' ".cursor/rules/RULESET.mdc" ;;
    github-copilot) printf '%s' ".github/copilot-instructions.md" ;;
    gemini-cli)     printf '%s' "GEMINI.md" ;;
    goose)          printf '%s' ".goosehints" ;;
    *)              printf '' ;;
  esac
}

# Per-harness GLOBAL (user-level) instruction file, where one exists.
harness_global() {
  case "$1" in
    claude-code) printf '%s' "${HOME}/.claude/CLAUDE.md" ;;
    codex|agents) printf '%s' "${HOME}/.codex/AGENTS.md" ;;
    *)           printf '' ;;
  esac
}

usage() {
  cat <<'EOF'
Render a rules-hive ruleset into agent instruction files.

Options:
  --ruleset NAME    Ruleset under rules/ (default: queen-charter)
  --harness NAME    Target harness (repeatable): agents, claude-code, cursor,
                    codex, gemini-cli, goose, opencode, kiro, github-copilot,
                    databricks-genie-code, snowflake-cortex-code
  --dir PATH        Project directory to write into (default: current dir)
  --global          Write to the user-level file where supported
  -h, --help        Show this help

Default harnesses (if none given): agents claude-code cursor github-copilot gemini-cli
EOF
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
    gpath="$(harness_global "$harness")"
    if [ -z "$gpath" ]; then
      echo "skip: $harness has no user-level instruction file (use project scope)" >&2
      continue
    fi
    write_file "$gpath" "$harness"
  else
    rel="$(harness_relpath "$harness")"
    if [ -z "$rel" ]; then
      echo "unknown harness: $harness" >&2
      exit 1
    fi
    rel="$(printf '%s' "$rel" | sed "s/RULESET/${RULESET}/")"
    write_file "${TARGET_DIR%/}/$rel" "$harness"
  fi
done

echo "done."
