#!/usr/bin/env bash
# Zoho Books Free-plan API check. Run on your own Mac; nothing is written to disk.
#
# Before running, in https://api-console.zoho.com choose Self Client, Generate Code,
# scope:  ZohoBooks.settings.READ   duration: 10 minutes.
# You will be asked for the Client ID, Client Secret and that code. Input is hidden.
#
# What it prints: the HTTP status of the token exchange and of GET /books/v3/organizations,
# the organization name, id and plan fields, and the refresh token ONCE so you can save it
# in your password manager (it is needed later for the Phase 4 sync and A5). Nothing else.
set -euo pipefail

ACCOUNTS="${ZOHO_ACCOUNTS:-https://accounts.zoho.com}"   # use accounts.zoho.eu etc. if your Zoho is not on .com

read -r -s -p "Client ID: " CID; echo
read -r -s -p "Client Secret: " CSEC; echo
read -r -s -p "Grant code (from Self Client, Generate Code): " CODE; echo

tok_body=$(mktemp -t zb) ; trap 'rm -f "$tok_body" "$org_body"' EXIT
tok_status=$(curl -s -o "$tok_body" -w '%{http_code}' -X POST "$ACCOUNTS/oauth/v2/token" \
  -d "grant_type=authorization_code" -d "client_id=$CID" -d "client_secret=$CSEC" -d "code=$CODE")
unset CSEC CODE
echo "Token exchange HTTP status: $tok_status"

ACCESS=$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("access_token",""))' "$tok_body")
REFRESH=$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("refresh_token",""))' "$tok_body")
API=$(python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("api_domain","https://www.zohoapis.com"))' "$tok_body")
if [ -z "$ACCESS" ]; then
  echo "No access token returned. Zoho's reply (no secrets in it):"
  python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); print({k:v for k,v in d.items() if k in ("error","error_description")})' "$tok_body"
  exit 1
fi

org_body=$(mktemp -t zb)
org_status=$(curl -s -o "$org_body" -w '%{http_code}' "$API/books/v3/organizations" \
  -H "Authorization: Zoho-oauthtoken $ACCESS")
unset ACCESS
echo "GET /books/v3/organizations HTTP status: $org_status"
python3 -I - "$org_body" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("code:", d.get("code"), "message:", d.get("message"))
for o in d.get("organizations", []):
    keep = {k: o.get(k) for k in ("name", "organization_id", "plan_name", "plan_type", "plan_period", "is_default_org", "currency_code", "time_zone") if k in o}
    print(keep)
PY

echo
echo "Refresh token (save in your password manager now; it is not shown again and not stored here):"
echo "$REFRESH"
unset REFRESH
