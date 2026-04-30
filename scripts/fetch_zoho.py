import os
import json
import requests
from datetime import datetime, timezone

ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_ITEMS_URL = "https://www.zohoapis.com/inventory/v1/items"
ZOHO_COMPOSITE_ITEMS_URL = "https://www.zohoapis.com/inventory/v1/compositeitems"
ZOHO_BUNDLES_URL = "https://www.zohoapis.com/inventory/v1/bundles"

PRODUCTION_TYPES = {"Finished Product / Sales Product", "Subassembly"}


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


def fetch_all_pages(url, headers, params, data_key):
    results = []
    page = 1
    while True:
        p = {**params, "page": page, "per_page": 200}
        resp = requests.get(url, headers=headers, params=p)
        if not resp.ok:
            print(f"  HTTP {resp.status_code} — {resp.text[:300]}")
            resp.raise_for_status()
        body = resp.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"Zoho API error: {body.get('message')} (code {body.get('code')})")
        records = body.get(data_key, [])
        results.extend(records)
        if not body.get("page_context", {}).get("has_more_page", False):
            break
        page += 1
    return results


def get_cf_item_type(item):
    for cf in item.get("custom_fields", []):
        if cf.get("api_name") == "cf_item_type":
            return cf.get("value")
    return None


def update_index(index_file, month_str):
    if os.path.exists(index_file):
        with open(index_file) as f:
            months = json.load(f)
    else:
        months = []
    if month_str not in months:
        months.append(month_str)
    months.sort(reverse=True)
    with open(index_file, "w") as f:
        json.dump(months, f, indent=2)
    return months


def main():
    client_id = os.environ["ZOHO_CLIENT_ID"]
    client_secret = os.environ["ZOHO_CLIENT_SECRET"]
    refresh_token = os.environ["ZOHO_REFRESH_TOKEN"]
    org_id = os.environ["ZOHO_ORG_ID"]

    print("Refreshing access token...")
    access_token = get_access_token(client_id, client_secret, refresh_token)
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    now = datetime.now(timezone.utc)
    month_str = now.strftime("%Y-%m")
    month_prefix = now.strftime("%Y-%m-")

    print("Fetching items (for cf_item_type map)...")
    all_items = fetch_all_pages(
        ZOHO_ITEMS_URL,
        headers,
        {"organization_id": org_id},
        "items",
    )
    item_type_map = {
        str(item["item_id"]): get_cf_item_type(item)
        for item in all_items
        if item.get("item_id")
    }
    print(f"  Built type map for {len(item_type_map)} items")

    print("Fetching composite items...")
    all_composite_items = fetch_all_pages(
        ZOHO_COMPOSITE_ITEMS_URL,
        headers,
        {"organization_id": org_id},
        "composite_items",
    )

    production_items = []
    for item in all_composite_items:
        cf_item_type = item_type_map.get(str(item.get("composite_item_id", "")))
        if cf_item_type in PRODUCTION_TYPES:
            production_items.append({
                "composite_item_id": item["composite_item_id"],
                "name": item.get("name", ""),
                "cf_item_type": cf_item_type,
            })

    print(f"  {len(all_composite_items)} composite items total, {len(production_items)} are production items (Finished / Subassembly)")

    fp_in_production = []
    fp_completed = []
    sa_in_production = []
    sa_completed = []

    print(f"Fetching bundles for {len(production_items)} items (filtering to {month_str})...")
    for i, item in enumerate(production_items, 1):
        bundles = fetch_all_pages(
            ZOHO_BUNDLES_URL,
            headers,
            {"organization_id": org_id, "composite_item_id": item["composite_item_id"]},
            "bundles",
        )

        month_bundles = [b for b in bundles if b.get("date", "").startswith(month_prefix)]

        if month_bundles:
            print(f"  [{i}/{len(production_items)}] {item['name']}: {len(month_bundles)} bundle(s) this month")

        for bundle in month_bundles:
            record = {
                "assembly_number": (
                    bundle.get("bundle_number")
                    or bundle.get("reference_number")
                    or ""
                ),
                "item_name": item["name"],
                "quantity": bundle.get("quantity_to_bundle", 0),
                "date": bundle.get("date", ""),
            }

            is_completed = bundle.get("is_completed", False)

            if item["cf_item_type"] == "Finished Product / Sales Product":
                if is_completed:
                    fp_completed.append(record)
                else:
                    fp_in_production.append(record)
            else:
                if is_completed:
                    sa_completed.append(record)
                else:
                    sa_in_production.append(record)

    print(f"\nResults for {month_str}:")
    print(f"  Finished Products  — In Production: {len(fp_in_production)}, Completed: {len(fp_completed)}")
    print(f"  Subassemblies      — In Production: {len(sa_in_production)}, Completed: {len(sa_completed)}")

    output = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "month": month_str,
        "finished_products": {
            "in_production": fp_in_production,
            "completed": fp_completed,
        },
        "subassemblies": {
            "in_production": sa_in_production,
            "completed": sa_completed,
        },
    }

    os.makedirs("data", exist_ok=True)

    month_file = f"data/{month_str}.json"
    with open(month_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {month_file}")

    with open("data/latest.json", "w") as f:
        json.dump(output, f, indent=2)
    print("Wrote data/latest.json")

    months = update_index("data/index.json", month_str)
    print(f"Wrote data/index.json — available months: {months}")


if __name__ == "__main__":
    main()
