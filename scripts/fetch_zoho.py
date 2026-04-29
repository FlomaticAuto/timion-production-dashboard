import os
import requests

ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"


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


def probe(headers, org_id):
    candidates = [
        # v2 API
        "https://www.zohoapis.com/inventory/v2/assemblyorders",
        # alternative host
        "https://inventory.zoho.com/api/v1/assemblyorders",
        # known-good endpoints to confirm auth scope
        "https://www.zohoapis.com/inventory/v1/salesorders",
        "https://www.zohoapis.com/inventory/v1/purchaseorders",
        # composite item detail (contains assembly info?)
        "https://www.zohoapis.com/inventory/v1/compositeitems?page=1&per_page=1",
    ]
    params_base = {"organization_id": org_id, "per_page": 1}

    for url in candidates:
        resp = requests.get(url, headers=headers, params=params_base)
        keys = ""
        if resp.ok:
            try:
                keys = list(resp.json().keys())
            except Exception:
                pass
        snippet = resp.text[:200].replace("\n", " ")
        print(f"  [{resp.status_code}] {url.split('zoho')[1]}: keys={keys} | {snippet[:120]}")

    # Check full composite item response keys for assembly-related fields
    print("\n--- Composite item detail keys ---")
    r = requests.get("https://www.zohoapis.com/inventory/v1/compositeitems", headers=headers, params={"organization_id": org_id, "per_page": 1})
    if r.ok:
        body = r.json()
        items = body.get("composite_items", [])
        if items:
            cid = items[0].get("composite_item_id") or items[0].get("item_id")
            r2 = requests.get(f"https://www.zohoapis.com/inventory/v1/compositeitems/{cid}", headers=headers, params={"organization_id": org_id})
            if r2.ok:
                detail = r2.json().get("composite_item", {})
                print(f"  Top-level keys: {list(detail.keys())}")


def main():
    client_id = os.environ["ZOHO_CLIENT_ID"]
    client_secret = os.environ["ZOHO_CLIENT_SECRET"]
    refresh_token = os.environ["ZOHO_REFRESH_TOKEN"]
    org_id = os.environ["ZOHO_ORG_ID"]

    print("Refreshing access token...")
    access_token = get_access_token(client_id, client_secret, refresh_token)
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    print("--- Probing endpoints ---")
    probe(headers, org_id)


if __name__ == "__main__":
    main()
