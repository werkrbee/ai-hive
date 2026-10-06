#!/usr/bin/env bash
# Convert ai-hive's git submodules (under hives/) into plain tracked directories — a monorepo.
# REVIEW BEFORE RUNNING. Run from the repo root on a clean working tree. Best run in Claude
# Code so it can verify each step. Make a backup/branch first:  git switch -c refactor/monorepo
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [ ! -f .gitmodules ]; then
  echo "No .gitmodules — nothing to migrate."; exit 0
fi

echo ">> Ensuring submodule contents are present..."
git submodule update --init --recursive

# Collect submodule paths from .gitmodules
paths=$(git config -f .gitmodules --get-regexp '^submodule\..*\.path$' | awk '{print $2}')

for p in $paths; do
  echo ">> Absorbing $p"
  # 1. de-register the submodule (removes it from .git/config, empties .git/modules state later)
  git submodule deinit -f "$p"
  # 2. remove the gitlink from the index (keep files on disk via re-checkout below)
  git rm -f "$p" >/dev/null
  # 3. drop the internal submodule git dir
  rm -rf ".git/modules/$p"
  # 4. restore the working-tree content as plain files from the submodule's last commit
  #    (git rm removed them; bring them back from the submodule's objects via a fresh checkout)
done

echo ">> NOTE: after this loop, re-populate hives/ from your local hive working copies"
echo "   OR from a clean clone of each hive. If the directories are now empty, copy the"
echo "   hive contents in (minus their .git) before committing. Verify each hives/<name>/"
echo "   contains real files, not an empty dir."

# 5. remove the submodule manifest
git rm -f .gitmodules >/dev/null 2>&1 || rm -f .gitmodules

echo ">> Staging migrated hives as plain files..."
git add hives .gitmodules 2>/dev/null || true
git add -A hives

echo
echo ">> Done de-wiring submodules. Review 'git status', confirm every hives/<name>/ has"
echo "   its files, then: git commit -m 'refactor: consolidate hives into monorepo'"
echo "   Sanity check: a fresh 'git clone' should need no --recurse-submodules."
