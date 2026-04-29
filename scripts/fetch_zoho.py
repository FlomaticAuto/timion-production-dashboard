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
    candidates = [
        f"{BASE}/manufacture",
        f"{BASE}/manufacture/orders",
        f"{BASE}/workorders",
        f"{BASE}/work_orders",
        f"{BASE}/assembly",
        f"{BASE}/assembly/orders",
        f"{BASE}/production",
        f"{BASE}/productionorders",
        f"{BASE}/reports/assemblyorders",
        f"{BASE}/reports/assembly_orders",
        f"{BASE}/reports",
        f"{BASE}/",
    ]
    params = {"organization_id": org_id, "per_page": 1}
    for url in candidates:
        resp = requests.get(url, headers=headers, params=params)
        snippet = resp.text[:150].replace("\n", " ")
        print(f"  [{resp.status_code}] ...{url.split('/v1')[1] or '/'}: {snippet}")


def main():
    client_id = os.environ["ZOHO_CLIENT_ID"]
    client_secret = os.environ["ZOHO_CLIENT_SECRET"]
    refresh_token = os.environ["ZOHO_REFRESH_TOKEN"]
    org_id = os.environ["ZOHO_ORG_ID"]

    print("Refreshing access token...")
    access_token = get_access_token(client_id, client_secret, refresh_token)
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    print("--- Probing remaining candidates ---")
    probe(headers, org_id)


if __name__ == "__main__":
    main()
