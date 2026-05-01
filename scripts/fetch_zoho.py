import argparse
import os
import json
import time
import requests
from datetime import datetime, timezone

ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_COMPOSITE_ITEMS_URL = "https://www.zohoapis.com/inventory/v1/compositeitems"
ZOHO_BUNDLES_URL = "https://www.zohoapis.com/inventory/v1/bundles"

PRODUCTION_TYPES = {"Finished Product / Sales Product", "Subassembly"}
ITEM_TYPE_CACHE_FILE = "data/item_type_cache.json"


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


def get_custom_field(item, api_name):
    for cf in item.get("custom_fields") or []:
        if cf.get("api_name") == api_name:
            return cf.get("value")
    return None


def get_cf_item_type(item):
    return get_custom_field(item, "cf_item_type")


def normalise_multiselect(value):
    """Return a list regardless of whether Zoho gives a string, list, or None."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [s.strip() for s in str(value).split(",") if s.strip()]


def load_item_type_cache(today_str):
    if not os.path.exists(ITEM_TYPE_CACHE_FILE):
        return {}
    try:
        with open(ITEM_TYPE_CACHE_FILE) as f:
            data = json.load(f)
        if data.get("date") == today_str:
            print(f"  Using today's cached item type map ({len(data['map'])} entries)")
            return data["map"]
    except Exception:
        pass
    return {}


def save_item_type_cache(type_map, today_str):
    with open(ITEM_TYPE_CACHE_FILE, "w") as f:
        json.dump({"date": today_str, "map": type_map}, f)


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", metavar="YYYY-MM",
                        help="Month to fetch. Defaults to current month.")
    args = parser.parse_args()

    client_id = os.environ["ZOHO_CLIENT_ID"]
    client_secret = os.environ["ZOHO_CLIENT_SECRET"]
    refresh_token = os.environ["ZOHO_REFRESH_TOKEN"]
    org_id = os.environ["ZOHO_ORG_ID"]

    print("Refreshing access token...")
    access_token = get_access_token(client_id, client_secret, refresh_token)
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    now_month_str = now.strftime("%Y-%m")
    month_str = args.month or now_month_str
    month_prefix = f"{month_str}-"
    print(f"Target month: {month_str}")

    print("Fetching composite items list...")
    all_composite_items = fetch_all_pages(
        ZOHO_COMPOSITE_ITEMS_URL,
        headers,
        {"organization_id": org_id},
        "composite_items",
    )
    print(f"  {len(all_composite_items)} composite items found")

    print("Building item type map (cache where available, API for new/missing)...")
    type_cache = load_item_type_cache(today_str)
    production_items = []
    new_entries = 0
    for i, item in enumerate(all_composite_items, 1):
        if i % 100 == 0:
            print(f"  {i}/{len(all_composite_items)} processed...")
        item_id = str(item["composite_item_id"])
        if item_id in type_cache:
            cf_item_type = type_cache[item_id]
        else:
            resp = requests.get(
                f"{ZOHO_COMPOSITE_ITEMS_URL}/{item_id}",
                headers=headers,
                params={"organization_id": org_id},
            )
            time.sleep(0.15)
            cf_item_type = None
            if resp.ok:
                body = resp.json()
                if body.get("code", 0) == 0:
                    cf_item_type = get_cf_item_type(body.get("composite_item", {}))
            type_cache[item_id] = cf_item_type
            new_entries += 1

        if cf_item_type in PRODUCTION_TYPES:
            production_items.append({
                "composite_item_id": item["composite_item_id"],
                "name": item.get("name", ""),
                "cf_item_type": cf_item_type,
            })

    if new_entries > 0:
        save_item_type_cache(type_cache, today_str)
        print(f"  Cache updated with {new_entries} new entries")
    print(f"  {len(production_items)} are production items (Finished Product / Subassembly)")

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
            # Fetch bundle detail to get custom fields (not in list response)
            detail_resp = requests.get(
                f"{ZOHO_BUNDLES_URL}/{bundle['bundle_id']}",
                headers=headers,
                params={"organization_id": org_id},
            )
            bundle_detail = {}
            if detail_resp.ok:
                detail_body = detail_resp.json()
                if detail_body.get("code", 0) == 0:
                    bundle_detail = detail_body.get("bundle", {})

            production_staff = normalise_multiselect(
                get_custom_field(bundle_detail, "cf_production_staff")
            )
            serial_numbers = bundle_detail.get("finished_product_serial_numbers") or []

            record = {
                "assembly_number": bundle.get("reference_number", ""),
                "item_name": item["name"],
                "quantity": bundle.get("quantity_to_bundle", 0),
                "date": bundle.get("date", ""),
                "status": bundle.get("status", ""),
                "production_staff": production_staff,
                "serial_numbers": serial_numbers,
            }

            is_completed = bundle.get("status") == "bundled"

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

    if month_str == now_month_str:
        with open("data/latest.json", "w") as f:
            json.dump(output, f, indent=2)
        print("Wrote data/latest.json")
    else:
        print(f"Skipping latest.json update (backfill run for {month_str})")

    months = update_index("data/index.json", month_str)
    print(f"Wrote data/index.json — available months: {months}")


if __name__ == "__main__":
    main()
