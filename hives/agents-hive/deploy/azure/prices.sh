#!/usr/bin/env bash
# Look up Foundry models' list prices in Azure's public Retail Prices API, so the prices in
# main.bicepparam can be checked with one command. The Foundry model catalog carries no
# reliable prices, and meter names follow no rule across publishers (GPT-5.4's input is
# "5.4 inp Gl", DeepSeek-V3.2's "V3.2 Inp glbl"), so this prints the meters and leaves the
# choice to you; it doesn't set any price. Prices per thousand tokens are shown per million,
# the unit main.bicepparam uses.
#
# Usage: ./prices.sh <region>                            the region's Foundry products
#        ./prices.sh <region> <product> [<sku-prefix>]   that product's meters
#
#   ./prices.sh eastus2 "Azure OpenAI GPT5" "5.4 "        GPT-5.4: "5.4 inp Gl", "5.4 opt Gl"
#   ./prices.sh eastus2 "Azure Deepseek Models" "V3.2 "   DeepSeek-V3.2: "... Inp glbl", "... Outp glbl"
#
# "Gl" or "glbl" in a meter is the GlobalStandard sku, "DZ" or "Dz" DataZoneStandard. Needs
# curl and python3; no sign-in.
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
  echo "usage: $0 <region> [<product> [<sku-prefix>]]" >&2
  exit 2
fi
region=$1 product=${2:-} prefix=${3:-}
q() { local s="'"; printf "'%s'" "${1//$s/$s$s}"; }  # an OData string literal

filter="serviceName eq 'Foundry Models' and armRegionName eq $(q "$region")"
[ -n "$product" ] && filter="$filter and productName eq $(q "$product")"
[ -n "$prefix" ] && filter="$filter and startswith(skuName, $(q "$prefix"))"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# The API pages its results and limits how fast it's called; curl's --retry waits out a 429.
n=0
args=(-G "https://prices.azure.com/api/retail/prices" --data-urlencode "\$filter=$filter")
while :; do
  n=$((n + 1))
  if ! curl -sSf --retry 5 --retry-delay 10 "${args[@]}" -o "$tmp/$n.json"; then
    echo "error: couldn't read the Retail Prices API" >&2
    exit 1
  fi
  next=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("NextPageLink") or "")' "$tmp/$n.json")
  [ -z "$next" ] && break
  args=("$next")
done

python3 - "$region" "$product" "$tmp" <<'PY'
import json, sys
from pathlib import Path

region, product, tmp = sys.argv[1], sys.argv[2], Path(sys.argv[3])
items = [i for p in sorted(tmp.glob("*.json"), key=lambda p: int(p.stem))
         for i in json.loads(p.read_text())["Items"] if i.get("type") == "Consumption"]
if not items:
    print(f"error: no Foundry Models prices match in {region}", file=sys.stderr)
    sys.exit(1)
if not product:
    for name in sorted({i["productName"] for i in items}):
        print(name)
    sys.exit(0)
per = {"1K": 1000, "1M": 1}  # to USD per million tokens
for i in sorted(items, key=lambda i: i["skuName"]):
    unit = i["unitOfMeasure"]
    price = f"{i['retailPrice'] * per[unit]:g} USD per million tokens" if unit in per \
        else f"{i['retailPrice']:g} USD per {unit}"
    print(f"{i['skuName']}: {price} (since {i['effectiveStartDate'][:10]})")
PY
