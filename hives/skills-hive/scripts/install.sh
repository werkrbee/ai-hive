#!/usr/bin/env bash
# Install skills from this repo into one or more agent harnesses.
# Usage:
#   ./scripts/install.sh                    # interactive (defaults: barry -> cursor)
#   ./scripts/install.sh --global --harness cursor --skill barry
#   ./scripts/install.sh --all --global --harness cursor --harness claude-code
#
# Written for macOS's default Bash 3.2 — no associative arrays, no mapfile.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_SRC="${REPO_ROOT}/skills"
GLOBAL=false
TARGETS=()
INSTALL_ALL_SKILLS=false
SKILL_NAMES=()

# Bash-3.2-safe harness lookup (replaces `declare -A`). Returns the global
# skills path for a harness label, or empty string if unknown.
harness_path() {
  case "$1" in
    claude-code)    printf '%s' "${HOME}/.claude/skills" ;;
    codex)          printf '%s' "${HOME}/.codex/skills" ;;
    cursor)         printf '%s' "${HOME}/.cursor/skills" ;;
    github-copilot) printf '%s' "${HOME}/.copilot/skills" ;;
    gemini-cli)     printf '%s' "${HOME}/.gemini/skills" ;;
    goose)          printf '%s' "${HOME}/.config/goose/skills" ;;
    opencode)       printf '%s' "${HOME}/.config/opencode/skills" ;;
    scout)          printf '%s' "${HOME}/.scout/skills" ;;
    kiro)                  printf '%s' "${HOME}/.kiro/skills" ;;          # AWS — verify path
    databricks-genie-code) printf '%s' "${HOME}/.databricks/skills" ;;    # workspace-based; verify
    snowflake-cortex-code) printf '%s' "${HOME}/.snowflake/skills" ;;     # workspace-based; verify
    agents)                printf '%s' "${HOME}/.agents/skills" ;;
    *)              printf '' ;;
  esac
}

usage() {
  cat <<'EOF'
Install werkrbee/skills-hive into agent harness directories.

Options:
  --global          Install to user-global paths (default: project .agents/skills/)
  --all             Install every skill in skills/
  --skill NAME      Install one skill (repeatable)
  --harness NAME    Target harness (repeatable): claude-code, codex, cursor,
                    github-copilot, gemini-cli, goose, opencode, scout, kiro,
                    databricks-genie-code, snowflake-cortex-code, agents
  -h, --help        Show this help

Examples:
  ./scripts/install.sh --global --harness cursor --skill barry
  ./scripts/install.sh --global --all --harness cursor --harness claude-code
  npx skills add werkrbee/skills-hive -g -a cursor -y   # preferred when available

Note: for Microsoft Scout on Windows, use scripts/install.ps1 (junctions +
m-settings.json), not this script.
EOF
}

copy_skill() {
  skill_name="$1"
  dest_root="$2"
  src="${SKILLS_SRC}/${skill_name}"
  dest="${dest_root}/${skill_name}"

  if [ ! -f "${src}/SKILL.md" ]; then
    echo "skip: ${skill_name} (no SKILL.md at ${src})" >&2
    return 1
  fi

  mkdir -p "${dest_root}"
  rm -rf "${dest}"
  cp -R "${src}" "${dest}"
  echo "installed: ${skill_name} -> ${dest}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --global) GLOBAL=true; shift ;;
    --all) INSTALL_ALL_SKILLS=true; shift ;;
    --skill) SKILL_NAMES+=("$2"); shift 2 ;;
    --harness) TARGETS+=("$2"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [ ${#TARGETS[@]} -eq 0 ]; then
  TARGETS=(cursor)
fi

if [ "$INSTALL_ALL_SKILLS" = true ]; then
  while IFS= read -r -d '' skill_dir; do
    SKILL_NAMES+=("$(basename "${skill_dir}")")
  done < <(find "${SKILLS_SRC}" -mindepth 1 -maxdepth 1 -type d -print0)
fi

if [ ${#SKILL_NAMES[@]} -eq 0 ]; then
  SKILL_NAMES=(barry)
fi

for harness in "${TARGETS[@]}"; do
  gpath="$(harness_path "$harness")"
  if [ -z "$gpath" ]; then
    echo "unknown harness: ${harness}" >&2
    exit 1
  fi

  if [ "$GLOBAL" = true ]; then
    dest_root="$gpath"
  else
    dest_root="${REPO_ROOT}/.agents/skills"
    if [ "$harness" = "cursor" ]; then
      dest_root="${REPO_ROOT}/.cursor/skills"
    elif [ "$harness" = "claude-code" ]; then
      dest_root="${REPO_ROOT}/.claude/skills"
    elif [ "$harness" = "goose" ]; then
      dest_root="${REPO_ROOT}/.goose/skills"
    fi
  fi

  for skill in "${SKILL_NAMES[@]}"; do
    copy_skill "${skill}" "${dest_root}" || true
  done
done

echo "done."
