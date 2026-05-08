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
LOOKBACK_MONTHS = 3  # re-process previous months with open items up to this many months back


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


def get_months_to_reprocess(index_file, current_month):
    """Return previous months within LOOKBACK_MONTHS that have open in_production records."""
    if not os.path.exists(index_file):
        return []
    try:
        with open(index_file) as f:
            months = json.load(f)
    except Exception:
        return []

    cur_year, cur_mon = map(int, current_month.split("-"))
    reprocess = []
    for m in months:
        if m >= current_month:
            continue
        m_year, m_mon = map(int, m.split("-"))
        months_ago = (cur_year - m_year) * 12 + (cur_mon - m_mon)
        if months_ago > LOOKBACK_MONTHS:
            continue
        data_file = f"data/{m}.json"
        if not os.path.exists(data_file):
            continue
        try:
            with open(data_file) as f:
                data = json.load(f)
        except Exception:
            continue
        has_open = (
            bool(data.get("finished_products", {}).get("in_production")) or
            bool(data.get("subassemblies", {}).get("in_production"))
        )
        if has_open:
            reprocess.append(m)
    return reprocess


def fetch_bundles_for_months(months, production_items, headers, org_id):
    """
    Single pass over all production items. Classifies each bundle into whichever
    target month it belongs to (by date prefix). Only makes detail API calls for
    bundles that match a target month.
    """
    month_prefixes = {m: f"{m}-" for m in months}
    results = {
        m: {"fp_in_production": [], "fp_completed": [], "sa_in_production": [], "sa_completed": []}
        for m in months
    }
    logged_keys = False

    for i, item in enumerate(production_items, 1):
        bundles = fetch_all_pages(
            ZOHO_BUNDLES_URL,
            headers,
            {"organization_id": org_id, "composite_item_id": item["composite_item_id"]},
            "bundles",
        )

        # Match each bundle to a target month
        relevant = []
        for b in bundles:
            bdate = b.get("date", "")
            for m, prefix in month_prefixes.items():
                if bdate.startswith(prefix):
                    relevant.append((m, b))
                    break

        if relevant:
            by_month = {}
            for m, _ in relevant:
                by_month[m] = by_month.get(m, 0) + 1
            parts = ", ".join(f"{m}: {c}" for m, c in sorted(by_month.items()))
            print(f"  [{i}/{len(production_items)}] {item['name']}: {parts}")

        for target_month, bundle in relevant:
            detail_resp = requests.get(
                f"{ZOHO_BUNDLES_URL}/{bundle['bundle_id']}",
                headers=headers,
                params={"organization_id": org_id},
            )
            bundle_detail = {}
            if detail_resp.ok:
                body = detail_resp.json()
                if body.get("code", 0) == 0:
                    bundle_detail = body.get("bundle", {})

            # Log all available keys on the first bundle to aid completion-date discovery
            if not logged_keys and bundle_detail:
                print(f"  [debug] bundle_detail keys: {sorted(bundle_detail.keys())}")
                logged_keys = True

            production_staff = normalise_multiselect(
                get_custom_field(bundle_detail, "cf_production_staff")
            )
            serial_numbers = bundle_detail.get("finished_product_serial_numbers") or []

            is_completed = bundle.get("status") == "bundled"

            # Try known candidate fields for completion date; expand once debug keys are known
            completed_date = (
                bundle_detail.get("bundled_date") or
                bundle_detail.get("assembled_date") or
                bundle_detail.get("last_modified_time") or
                ""
            )

            record = {
                "assembly_number": bundle.get("reference_number", ""),
                "item_name": item["name"],
                "quantity": bundle.get("quantity_to_bundle", 0),
                "date": bundle.get("date", ""),
                "status": bundle.get("status", ""),
                "production_staff": production_staff,
                "serial_numbers": serial_numbers,
            }
            if is_completed and completed_date:
                record["completed_date"] = completed_date

            bucket = results[target_month]
            is_fp = item["cf_item_type"] == "Finished Product / Sales Product"
            if is_fp:
                (bucket["fp_completed"] if is_completed else bucket["fp_in_production"]).append(record)
            else:
                (bucket["sa_completed"] if is_completed else bucket["sa_in_production"]).append(record)

    return results


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

    # Determine all months to process in this run
    prev_months = get_months_to_reprocess("data/index.json", month_str)
    all_months = [month_str] + prev_months
    if prev_months:
        print(f"Re-processing open months: {prev_months}")

    print(f"Fetching bundles for {len(production_items)} items across {len(all_months)} month(s)...")
    month_results = fetch_bundles_for_months(all_months, production_items, headers, org_id)

    os.makedirs("data", exist_ok=True)

    for m in all_months:
        r = month_results[m]
        print(f"\nResults for {m}:")
        print(f"  Finished Products  — In Production: {len(r['fp_in_production'])}, Completed: {len(r['fp_completed'])}")
        print(f"  Subassemblies      — In Production: {len(r['sa_in_production'])}, Completed: {len(r['sa_completed'])}")

        output = {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "month": m,
            "finished_products": {
                "in_production": r["fp_in_production"],
                "completed": r["fp_completed"],
            },
            "subassemblies": {
                "in_production": r["sa_in_production"],
                "completed": r["sa_completed"],
            },
        }

        month_file = f"data/{m}.json"
        with open(month_file, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Wrote {month_file}")

        if m == now_month_str:
            with open("data/latest.json", "w") as f:
                json.dump(output, f, indent=2)
            print("Wrote data/latest.json")
        else:
            print(f"Skipping latest.json (re-processed {m})")

    months = update_index("data/index.json", month_str)
    print(f"\nWrote data/index.json — available months: {months}")


if __name__ == "__main__":
    main()
