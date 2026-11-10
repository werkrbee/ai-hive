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

HOUSE_ROOT="$(cd "${REPO_ROOT}/../.." && pwd)"
REGISTRY_PY="${HOUSE_ROOT}/scripts/harnesses.py"

# Harness paths come from the House's registry (harnesses.json), read through
# scripts/harnesses.py. $1 is the scope (global or project), $2 the harness; prints
# its skills path, or nothing if the harness has none.
harness_path() {
  python3 "$REGISTRY_PY" path skills "$1" "$2" 2>/dev/null || true
}

usage() {
  cat <<'EOF'
Install skills-hive skills into agent harness directories.

Options:
  --global          Install to user-global paths (default: project .agents/skills/)
  --all             Install every skill in skills/
  --skill NAME      Install one skill (repeatable)
  --harness NAME    Target harness (repeatable); see the list below
  -h, --help        Show this help

Examples:
  ./scripts/install.sh --global --harness cursor --skill barry
  ./scripts/install.sh --global --all --harness cursor --harness claude-code
  npx skills add https://github.com/werkrbee/ai-hive/tree/main/hives/skills-hive -g -a cursor -y   # preferred when available

Note: for Microsoft Scout on Windows, use scripts/install.ps1 (junctions +
m-settings.json), not this script.

Harnesses with a skills path (from harnesses.json):
EOF
  python3 "$REGISTRY_PY" list --surface skills | sed 's/^/  /'
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

if ! command -v python3 >/dev/null; then
  echo "python3 is needed to read the harness registry (${HOUSE_ROOT}/harnesses.json)" >&2
  exit 1
fi

for harness in "${TARGETS[@]}"; do
  if [ "$GLOBAL" = true ]; then
    dest_root="$(harness_path global "$harness")"
  else
    rel="$(harness_path project "$harness")"
    dest_root="${rel:+${REPO_ROOT}/${rel}}"
  fi
  if [ -z "$dest_root" ]; then
    echo "unknown harness: ${harness}" >&2
    exit 1
  fi

  for skill in "${SKILL_NAMES[@]}"; do
    copy_skill "${skill}" "${dest_root}" || true
  done
done

echo "done."
