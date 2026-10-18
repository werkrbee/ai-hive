#!/usr/bin/env bash
# Exercise prices.sh against a stubbed curl: it builds the filter from its arguments, follows
# the API's pages, shows per-thousand prices per million, lists products when given none,
# and refuses when nothing matches or the API can't be read. Bash 3.2 safe; run it with
# /bin/bash on macOS.
#
# Usage: tests/prices_test.sh           (from hives/agents-hive/deploy/azure, or anywhere)
set -u

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
fail=0

# The stub writes $STUB/page1.json for the first call and page2.json for the NextPageLink;
# every call's arguments are appended to $STUB/calls. STUB_FAIL, when set, fails every call.
mkdir -p "$work/bin"
cat > "$work/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB/calls"
[ -n "${STUB_FAIL:-}" ] && { echo "curl: (22) The requested URL returned error: 503" >&2; exit 22; }
out= page=page1.json
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift ;;
    *next-page*) page=page2.json ;;
  esac
  shift
done
cp "$STUB/$page" "$out"
STUB
chmod +x "$work/bin/curl"

item() {  # SKU UNIT PRICE [TYPE]
  printf '{"productName": "Azure Deepseek Models", "skuName": "%s", "unitOfMeasure": "%s", "retailPrice": %s, "type": "%s", "effectiveStartDate": "2026-05-01T00:00:00Z"}' \
    "$1" "$2" "$3" "${4:-Consumption}"
}

# run CASE ARGS... — prices.sh with the pages in $PAGE1 and $PAGE2
run() {
  export STUB="$work/$1"; shift
  mkdir -p "$STUB"; : > "$STUB/calls"
  printf '%s' "$PAGE1" > "$STUB/page1.json"
  printf '%s' "${PAGE2:-}" > "$STUB/page2.json"
  out=$(PATH="$work/bin:$PATH" /bin/bash "$here/../prices.sh" "$@" 2>&1)
  code=$?
}
check() {  # LABEL CONDITION...
  local label="$1"; shift
  if "$@"; then echo "pass  $label"; else echo "FAIL  $label"; printf '%s\n' "$out" | sed 's/^/      /'; fail=1; fi
}
has() { printf '%s\n' "$out" | grep -q -- "$1"; }

PAGE1="{\"Items\": [$(item 'V3.2 Inp glbl' 1K 0.00058), $(item 'V3.2 Inp glbl' 1K 0.5 Reservation)], \"NextPageLink\": \"https://prices.azure.com/api/retail/prices?next-page\"}" \
PAGE2="{\"Items\": [$(item 'V3.2 Outp glbl' 1K 0.00168), $(item 'Provisioned Managed Global' 1/Hour 1.0)], \"NextPageLink\": null}" \
  run meters eastus2 "Azure Deepseek Models" "V3.2 "
check "meters: per-thousand prices shown per million, across both pages" \
  eval '[ "$code" -eq 0 ] && has "^V3.2 Inp glbl: 0.58 USD per million tokens (since 2026-05-01)" \
   && has "^V3.2 Outp glbl: 1.68 USD per million tokens"'
check "meters: other units are shown as they are, and reservations are left out" \
  eval 'has "^Provisioned Managed Global: 1 USD per 1/Hour" && [ "$(printf "%s\n" "$out" | wc -l)" -eq 3 ]'
check "meters: the filter names the service, region, product and sku prefix" \
  eval 'head -1 "$STUB/calls" | grep -q "serviceName eq .Foundry Models. and armRegionName eq .eastus2. and productName eq .Azure Deepseek Models. and startswith(skuName, .V3.2 .)" \
   && [ "$(wc -l < "$STUB/calls")" -eq 2 ]'

PAGE1="{\"Items\": [$(item 'V3.2 Inp glbl' 1K 0.00058)], \"NextPageLink\": null}" \
  run quote eastus2 "O'Brien Models"
check "a quote in an argument is escaped for OData" \
  grep -q "productName eq 'O''Brien Models'" "$STUB/calls"

PAGE1="{\"Items\": [$(item a 1M 1), $(item b 1M 2)], \"NextPageLink\": null}" run products eastus2
check "no product: lists the region's products once each" \
  eval '[ "$code" -eq 0 ] && [ "$out" = "Azure Deepseek Models" ]'

PAGE1='{"Items": [], "NextPageLink": null}' run none eastus2 "Nope"
check "nothing matches: refused" \
  eval '[ "$code" -ne 0 ] && has "no Foundry Models prices match in eastus2"'

PAGE1='{}' STUB_FAIL=1 run down eastus2 "Azure Deepseek Models"
check "API unreadable: refused" \
  eval '[ "$code" -ne 0 ] && has "couldn.t read the Retail Prices API"'

[ "$fail" -eq 0 ] && echo "OK  prices.sh checks passed"
exit "$fail"
