import os
import requests

ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
BASE = "https://www.zohoapis.com/inventory/v1"


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
    params = {"organization_id": org_id, "per_page": 2}

    candidates = [
        f"{BASE}/itemadjustments",
        f"{BASE}/inventoryadjustments",
        f"{BASE}/stockadjustments",
        f"{BASE}/transfers",
        f"{BASE}/inventoryhistory",
        f"{BASE}/stockhistory",
        f"{BASE}/journals",
        "https://www.zohoapis.com/books/v3/assemblyorders",
        "https://www.zohoapis.com/books/v3/itemadjustments",
    ]

    for url in candidates:
        resp = requests.get(url, headers=headers, params=params)
        snippet = resp.text[:200].replace("\n", " ")
        label = url.split("/v")[1] if "/v" in url else url
        print(f"  [{resp.status_code}] ...{label}: {snippet[:150]}")

    # Deep-dive item adjustments if it works
    print("\n--- Item adjustments detail ---")
    r = requests.get(f"{BASE}/itemadjustments", headers=headers, params={"organization_id": org_id, "per_page": 3})
    print(f"  HTTP {r.status_code}: {r.text[:600]}")


def main():
    client_id = os.environ["ZOHO_CLIENT_ID"]
    client_secret = os.environ["ZOHO_CLIENT_SECRET"]
    refresh_token = os.environ["ZOHO_REFRESH_TOKEN"]
    org_id = os.environ["ZOHO_ORG_ID"]

    print("Refreshing access token...")
    access_token = get_access_token(client_id, client_secret, refresh_token)
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    print("--- Probing ---")
    probe(headers, org_id)


if __name__ == "__main__":
    main()
