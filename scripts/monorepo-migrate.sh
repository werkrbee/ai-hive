#!/usr/bin/env bash
# Convert ai-hive's git submodules (under hives/) into plain tracked directories — a monorepo.
# Each hive is restored as ordinary files from the exact commit the superproject recorded,
# so the migrated tree matches the submodule SHAs. Hive history stays in each hive's own repo.
# Run from the repo root on a clean working tree, on a branch:  git switch -c refactor/monorepo
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [ ! -f .gitmodules ]; then
  echo "No .gitmodules — nothing to migrate."; exit 0
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is not clean. Commit or stash first." >&2; exit 1
fi

echo ">> Ensuring submodule contents are present..."
git submodule update --init

paths=$(git config -f .gitmodules --get-regexp '^submodule\..*\.path$' | awk '{print $2}')
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for p in $paths; do
  sha=$(git ls-tree HEAD "$p" | awk '$2 == "commit" {print $3}')
  if [ -z "$sha" ]; then
    echo "!! $p is not a recorded submodule gitlink; skipping" >&2; continue
  fi
  if [ -n "$(git -C "$p" status --porcelain)" ]; then
    echo "!! $p has uncommitted changes; commit them in the hive first" >&2; exit 1
  fi

  echo ">> Absorbing $p @ ${sha:0:7}"
  # 1. export the recorded commit's files before the submodule's git dir goes away
  mkdir -p "$tmp/$p"
  git -C "$p" archive "$sha" | tar -x -C "$tmp/$p"
  # 2. de-register the submodule and drop the gitlink and its internal git dir
  git submodule deinit -f "$p"
  git rm -q -f "$p"
  rm -rf ".git/modules/$p"
  # 3. restore the content as plain files and stage them
  rm -rf "$p"
  mkdir -p "$(dirname "$p")"
  mv "$tmp/$p" "$p"
  git add "$p"
done

git rm -q -f .gitmodules

echo
echo ">> Done. Every hive is now plain tracked files. Review 'git status', then:"
echo "   git commit -m 'refactor: consolidate hives into monorepo'"
echo "   Sanity check: a fresh 'git clone' needs no --recurse-submodules."
