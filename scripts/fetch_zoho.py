import os
import json
import calendar
import requests
from datetime import datetime, timezone

ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_BASE = "https://www.zohoapis.com/inventory/v1"
ZOHO_ITEMS_URL = f"{ZOHO_BASE}/items"


def get_access_token(client_id, client_secret, refresh_token):
    resp = requests.post(ZOHO_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    resp.raise_for_status()
    token_data = resp.json()
    if "access_token" not in token_data:
        raise RuntimeError(f"Token refresh failed: {token_data}")
    return token_data["access_token"]


def probe_endpoints(headers, org_id):
    """Try candidate assembly order endpoints and print results."""
    candidates = [
        f"{ZOHO_BASE}/assemblyorders",
        f"{ZOHO_BASE}/compositeitems/assemblyorders",
        f"{ZOHO_BASE}/assembly_orders",
        f"{ZOHO_BASE}/manufacturingorders",
        f"{ZOHO_BASE}/manufacturing_orders",
    ]
    params = {"organization_id": org_id, "per_page": 1}
    print("--- Probing assembly order endpoints ---")
    for url in candidates:
        resp = requests.get(url, headers=headers, params=params)
        snippet = resp.text[:200].replace("\n", " ")
        print(f"  {url.split('/v1/')[1]}: HTTP {resp.status_code} -> {snippet}")

    # Also try fetching composite items and then their assembly orders
    print("--- Trying composite items list ---")
    resp = requests.get(f"{ZOHO_BASE}/compositeitems", headers=headers, params={"organization_id": org_id, "per_page": 1})
    print(f"  compositeitems: HTTP {resp.status_code} -> {resp.text[:300].replace(chr(10), ' ')}")
    if resp.ok:
        body = resp.json()
        items = body.get("composite_items", [])
        if items:
            cid = items[0].get("item_id") or items[0].get("composite_item_id")
            print(f"  First composite item id: {cid}")
            if cid:
                r2 = requests.get(f"{ZOHO_BASE}/compositeitems/{cid}/assemblyorders", headers=headers, params={"organization_id": org_id})
                print(f"  compositeitems/{cid}/assemblyorders: HTTP {r2.status_code} -> {r2.text[:300].replace(chr(10), ' ')}")


def main():
    client_id = os.environ["ZOHO_CLIENT_ID"]
    client_secret = os.environ["ZOHO_CLIENT_SECRET"]
    refresh_token = os.environ["ZOHO_REFRESH_TOKEN"]
    org_id = os.environ["ZOHO_ORG_ID"]

    print("Refreshing access token...")
    access_token = get_access_token(client_id, client_secret, refresh_token)
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    probe_endpoints(headers, org_id)


if __name__ == "__main__":
    main()
