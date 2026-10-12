#!/usr/bin/env bash
# Exercise entra.sh against a stubbed az, one case per path: create, reuse, duplicate
# name, app not owned, failed lookup, and an answer other than yes. The stub reads the
# tenant from files and records every call that would change it, so each case can check
# that nothing changed before the prompt. Bash 3.2 safe; run it with /bin/bash on macOS.
#
# Usage: tests/entra_test.sh            (from hives/agents-hive/deploy/azure, or anywhere)
set -u

here=$(cd "$(dirname "$0")" && pwd)
entra="$here/../entra.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0

# The stub. Tenant state lives in $STUB: apps ("name appId owner"), sps ("appId spId"),
# roles ("appId roleId"), grants ("clientSp apiSp roleId"). Mutations are appended to
# $STUB/changes. STUB_FAIL, when set, is a pattern; a call whose arguments match it fails.
mkdir -p "$work/bin"
cat > "$work/bin/az" <<'STUB'
#!/usr/bin/env bash
args="$*"
if [ -n "${STUB_FAIL:-}" ] && printf '%s' "$args" | grep -q -- "$STUB_FAIL"; then
  echo "stub: failing: $args" >&2; exit 1
fi
touch "$STUB/apps" "$STUB/sps" "$STUB/roles" "$STUB/grants" "$STUB/changes"
quoted() { printf '%s' "$args" | sed -n "s/.*$1 '\([^']*\)'.*/\1/p"; }
case "$args" in
  "ad signed-in-user show"*) echo me ;;
  "ad app list"*) awk -v n="$(quoted 'displayName eq')" '$1==n{print $2}' "$STUB/apps" ;;
  "ad app owner list"*)
    id=$(printf '%s' "$args" | sed -n 's/.*--id \([^ ]*\).*/\1/p')
    awk -v i="$id" '$2==i && $3=="me"{c++} END{print c+0}' "$STUB/apps" ;;
  "ad sp list"*) awk -v a="$(quoted 'appId eq')" '$1==a{print $2}' "$STUB/sps" ;;
  "ad app show"*)
    id=$(printf '%s' "$args" | sed -n 's/.*--id \([^ ]*\).*/\1/p')
    awk -v i="$id" '$1==i{print $2}' "$STUB/roles" ;;
  "rest --method GET"*)
    sp=$(printf '%s' "$args" | sed -n 's#.*servicePrincipals/\([^/]*\)/appRoleAssignments.*#\1#p')
    api=$(printf '%s' "$args" | sed -n "s/.*resourceId=='\([^']*\)'.*/\1/p")
    role=$(printf '%s' "$args" | sed -n "s/.*appRoleId=='\([^']*\)'.*/\1/p")
    awk -v s="$sp" -v a="$api" -v r="$role" '$1==s && $2==a && $3==r{c++} END{print c+0}' "$STUB/grants" ;;
  "ad app create"*)
    name=$(printf '%s' "$args" | sed -n 's/.*--display-name \([^ ]*\).*/\1/p')
    id="app-$name"
    echo "$name $id -" >> "$STUB/apps"
    case "$args" in *--app-roles*) echo "$id role-1" >> "$STUB/roles" ;; esac
    echo "create $name" >> "$STUB/changes"; echo "$id" ;;
  "ad app owner add"*)  # like Graph: the creator isn't an owner until this runs
    id=$(printf '%s' "$args" | sed -n 's/.*--id \([^ ]*\).*/\1/p')
    awk -v i="$id" '$2==i{$3="me"} {print}' "$STUB/apps" > "$STUB/apps.new" && mv "$STUB/apps.new" "$STUB/apps"
    echo "$args" >> "$STUB/changes" ;;
  "ad sp create"*)
    id=$(printf '%s' "$args" | sed -n 's/.*--id \([^ ]*\).*/\1/p')
    echo "$id sp-$id" >> "$STUB/sps"; echo "sp create $id" >> "$STUB/changes"; echo "sp-$id" ;;
  *) echo "$args" >> "$STUB/changes" ;;
esac
STUB
chmod +x "$work/bin/az"

# run CASE ANSWER [CALLER...] — run entra.sh (for lineup and singularity by default),
# answering ANSWER
run() {
  export STUB="$work/$1"
  local answer="$2"; shift 2
  [ "$#" -gt 0 ] || set -- lineup singularity
  mkdir -p "$STUB"
  touch "$STUB/changes"
  out=$(printf '%s\n' "$answer" | PATH="$work/bin:$PATH" /bin/bash "$entra" "$@" 2>&1)
  code=$?
}
check() {  # LABEL CONDITION...
  local label="$1"; shift
  if "$@"; then echo "pass  $label"; else echo "FAIL  $label"; printf '%s\n' "$out" | sed 's/^/      /'; fail=1; fi
}
has() { printf '%s\n' "$out" | grep -q -- "$1"; }
unchanged() { [ ! -s "$STUB/changes" ]; }
seed() { mkdir -p "$work/$1"; cat > "$work/$1/$2"; }

# Create: an empty tenant. The plan says create for every app, and yes creates them.
run create yes
check "create: plan says create for each app" \
  has "patricia-a2a-api: create, with the Review.Request app role"
check "create: plan says create and grant for a caller" \
  has "lineup-patricia-client: create; grant Review.Request"
check "create: yes creates the apps and prints the parameters" \
  eval '[ "$code" -eq 0 ] && has "param allowedClients = \[.app-lineup-patricia-client., .app-singularity-patricia-client.\]"'
check "create: you own each app it creates" \
  eval '[ "$(grep -c "^ad app owner add" "$STUB/changes")" -eq 3 ]'
check "create: v2 tokens are set through Graph" \
  grep -q "rest --method PATCH.*requestedAccessTokenVersion.: 2" "$STUB/changes"
: > "$STUB/changes"
out=$(printf 'no\n' | PATH="$work/bin:$PATH" /bin/bash "$entra" lineup singularity 2>&1)
check "create: a re-run reuses all three apps and changes nothing" eval \
  'has "patricia-a2a-api: reuse app-patricia-a2a-api" && has "lineup-patricia-client: reuse" \
   && has "singularity-patricia-client: reuse" && unchanged'

# Anything but yes changes nothing, after showing the same plan.
run decline no
check "decline: plan shown, nothing changed" \
  eval '[ "$code" -ne 0 ] && has "Plan:" && has "stopped; nothing was changed" && unchanged'

# Reuse: everything exists; lineup already has the role, and singularity has only an
# assignment for a different role id, so it still needs the grant.
for c in reuse reuse-yes; do
  printf '%s\n' "patricia-a2a-api api-1 me" "lineup-patricia-client c-1 me" \
    "singularity-patricia-client c-2 me" | seed $c apps
  printf '%s\n' "api-1 sp-api" "c-1 sp-1" "c-2 sp-2" | seed $c sps
  echo "api-1 role-1" | seed $c roles
  printf '%s\n' "sp-1 sp-api role-1" "sp-2 sp-api role-old" | seed $c grants
done
run reuse no
check "reuse: plan says reuse with the appId" has "patricia-a2a-api: reuse api-1"
check "reuse: plan knows lineup already has the role" \
  has "lineup-patricia-client: reuse c-1; already has Review.Request"
check "reuse: plan grants singularity the role" \
  has "singularity-patricia-client: reuse c-2; grant Review.Request"
check "reuse: nothing changed on no" unchanged

# Saying yes to that plan does what it said: one grant, and no new apps.
run reuse-yes yes
check "reuse: yes grants only the missing role and creates no app" eval \
  '[ "$code" -eq 0 ] && [ "$(grep -c "rest --method POST" "$STUB/changes")" -eq 1 ] \
   && grep -q "sp-2" "$STUB/changes" && ! grep -q "^create \|^sp create" "$STUB/changes"'

# A caller named twice is refused before anything else.
run twice yes lineup lineup
check "caller named twice: refused" \
  eval '[ "$code" -eq 2 ] && has "named more than once" && unchanged'

# Refusals: each stops before the prompt, so the plan is never shown and nothing changes.
refused() { [ "$code" -ne 0 ] && ! has "Plan:" && unchanged; }

printf '%s\n' "patricia-a2a-api api-1 me" "patricia-a2a-api api-2 me" | seed duplicate apps
run duplicate yes
check "duplicate name: refused before the prompt" \
  eval 'refused && has "more than one app is named patricia-a2a-api"'

echo "lineup-patricia-client c-1 someone-else" | seed notowned apps
run notowned yes
check "not owned: refused before the prompt, with the fix" \
  eval 'refused && has "exists but you don.t own it" && has "az ad app owner add --id c-1"'

echo "patricia-a2a-api api-1 me" | seed norole apps
run norole yes
check "API app without the role: refused before the prompt" \
  eval 'refused && has "has no Review.Request app role"'

for pattern in "ad app list" "ad app owner list" "ad sp list" "ad app show" "rest --method GET"; do
  printf '%s\n' "patricia-a2a-api api-1 me" "lineup-patricia-client c-1 me" | seed "fail-$pattern" apps
  printf '%s\n' "api-1 sp-api" "c-1 sp-1" | seed "fail-$pattern" sps
  echo "api-1 role-1" | seed "fail-$pattern" roles
  STUB_FAIL="$pattern" run "fail-$pattern" yes
  check "failed lookup ($pattern): refused before the prompt" \
    eval 'refused && has "stub: failing" && ! has "error:"'
done

[ "$fail" -eq 0 ] && echo "OK  entra.sh checks passed"
exit "$fail"
