#!/usr/bin/env bash
# Exercise deploy.sh's role id check against a stubbed az: the current ids pass and reach
# the first what-if; a wrong id, or a lookup that fails, stops before any what-if or
# change. Each case runs deploy.sh from a throwaway git checkout, since it deploys only a
# clean one. Bash 3.2 safe; run it with /bin/bash on macOS.
#
# Usage: tests/deploy_test.sh           (from hives/agents-hive/deploy/azure, or anywhere)
set -u

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0

# The stub. $STUB/roles holds the subscription's role definitions ("id name"); every call
# is appended to $STUB/calls. STUB_FAIL, when set, is a pattern; a call whose arguments
# match it fails.
mkdir -p "$work/bin"
cat > "$work/bin/az" <<'STUB'
#!/usr/bin/env bash
args="$*"
echo "$args" >> "$STUB/calls"
if [ -n "${STUB_FAIL:-}" ] && printf '%s' "$args" | grep -q -- "$STUB_FAIL"; then
  echo "stub: failing: $args" >&2; exit 1
fi
case "$args" in
  "role definition list"*)
    id=$(printf '%s' "$args" | sed -n 's/.*--name \([^ ]*\).*/\1/p')
    awk -v i="$id" '$1==i{$1=""; sub(/^ /, ""); print}' "$STUB/roles" ;;
  "group exists"*) echo true ;;
  "deployment group what-if"*) echo "what-if shown" ;;
esac
STUB
chmod +x "$work/bin/az"

# run CASE BICEP — deploy.sh from a clean checkout holding BICEP as main.bicep, answering
# no at the first prompt
run() {
  export STUB="$work/$1"
  local repo="$STUB/repo" dir="$STUB/repo/hives/agents-hive/deploy/azure"
  mkdir -p "$dir"
  printf '%s\n' "7f951dda-4ed3-4680-a7ca-43fe172d538d AcrPull" \
    "a97b65f3-24c7-4388-baec-2e87135dc908 Cognitive Services User" > "$STUB/roles"
  : > "$STUB/calls"
  cp "$here/../deploy.sh" "$dir/"
  cp "$2" "$dir/main.bicep"
  git -C "$repo" init -q
  git -C "$repo" add -A
  git -C "$repo" -c user.name=test -c user.email=test@example.com commit -q -m test
  out=$(printf 'no\n' | PATH="$work/bin:$PATH" /bin/bash "$dir/deploy.sh" rg-test eastus2 p.bicepparam 2>&1)
  code=$?
}
check() {  # LABEL CONDITION...
  local label="$1"; shift
  if "$@"; then echo "pass  $label"; else echo "FAIL  $label"; printf '%s\n' "$out" | sed 's/^/      /'; fail=1; fi
}
has() { printf '%s\n' "$out" | grep -q -- "$1"; }
# Only role lookups ran: no what-if, no resource group, no deployment.
only_lookups() { ! grep -qv "^role definition list" "$STUB/calls"; }

bicep="$here/../main.bicep"

# The current ids exist, so the check passes and deploy.sh goes on to the first what-if.
run ok "$bicep"
check "current ids: both found by name" \
  eval 'has "acrPull: 7f951dda-4ed3-4680-a7ca-43fe172d538d (AcrPull)" \
   && has "cognitiveServicesUser: a97b65f3-24c7-4388-baec-2e87135dc908 (Cognitive Services User)"'
check "current ids: goes on to the first what-if" \
  eval 'has "== 1/3 infrastructure" && grep -q "^deployment group what-if" "$STUB/calls"'

# The id the first deploy had wrong: refused, naming it, before anything else.
sed 's/7f951dda-4ed3-4680-a7ca-43fe172d538d/7f951dde-4ef9-41c1-b0ac-8f2d6ec5c76b/' "$bicep" > "$work/wrong.bicep"
run wrong "$work/wrong.bicep"
check "wrong id: refused before any what-if, naming the id" \
  eval '[ "$code" -ne 0 ] && has "role definition 7f951dde-4ef9-41c1-b0ac-8f2d6ec5c76b (acrPull) doesn.t exist" \
   && ! has "== 1/3" && only_lookups'

# A lookup that fails is a refusal too, not a pass.
STUB_FAIL="role definition list" run lookup "$bicep"
check "failed lookup: refused before any what-if" \
  eval '[ "$code" -ne 0 ] && has "couldn.t look up role definition" && ! has "== 1/3" && only_lookups'

# A main.bicep the check can't read is refused rather than passed unchecked.
sed '/^var acrPull = /d' "$bicep" > "$work/unnamed.bicep"
run unnamed "$work/unnamed.bicep"
check "role var not found: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "can.t find the role id acrPull names" && [ ! -s "$STUB/calls" ]'

sed 's/subscriptionResourceId(.Microsoft.Authorization\/roleDefinitions., \([A-Za-z]*\))/\1/' \
  "$bicep" > "$work/none.bicep"
run none "$work/none.bicep"
check "no readable role assignments: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "found no role assignments" && [ ! -s "$STUB/calls" ]'

# An assignment written another way is refused, not skipped.
awk '!done && /roleDefinitionId: subscriptionResourceId/ {sub(/subscriptionResourceId\([^)]*\)/, "acrPull"); done=1} {print}' \
  "$bicep" > "$work/other.bicep"
run other "$work/other.bicep"
check "an assignment it can't read: refused before any lookup" \
  eval '[ "$code" -ne 0 ] && has "assigns 2 roles, but only" && [ ! -s "$STUB/calls" ]'

[ "$fail" -eq 0 ] && echo "OK  deploy.sh checks passed"
exit "$fail"
