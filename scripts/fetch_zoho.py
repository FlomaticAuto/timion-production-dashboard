import os
import json
import calendar
import requests
from datetime import datetime, timezone

ZOHO_TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_ITEMS_URL = "https://www.zohoapis.com/inventory/v1/items"
ZOHO_ASSEMBLY_URL = "https://www.zohoapis.com/inventory/v1/assemblyorders"


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
            print(f"  HTTP {resp.status_code} from {resp.url}")
            print(f"  Response: {resp.text[:500]}")
            resp.raise_for_status()
        body = resp.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"Zoho API error: {body.get('message')} (code {body.get('code')})")
        records = body.get(data_key, [])
        results.extend(records)
        page_context = body.get("page_context", {})
        if not page_context.get("has_more_page", False):
            break
        page += 1
        print(f"  Fetched page {page - 1}, has more: True")
    print(f"  Total {data_key}: {len(results)}")
    return results


def build_item_type_map(items):
    item_type_map = {}
    for item in items:
        item_id = item.get("item_id")
        if not item_id:
            continue
        cf_item_type = None
        for cf in item.get("custom_fields", []):
            if cf.get("api_name") == "cf_item_type":
                cf_item_type = cf.get("value")
                break
        item_type_map[str(item_id)] = cf_item_type
    return item_type_map


def make_record(order):
    return {
        "assembly_number": (
            order.get("assembly_order_number")
            or order.get("assembly_number")
            or order.get("document_number")
            or ""
        ),
        "item_name": (
            order.get("composite_item_name")
            or order.get("item_name")
            or ""
        ),
        "quantity": (
            order.get("quantity_to_manufacture")
            or order.get("quantity")
            or 0
        ),
        "date": order.get("date", ""),
    }


def classify_orders(assembly_orders, item_type_map):
    finished_in_production = []
    finished_completed = []
    subassemblies_in_production = []
    subassemblies_completed = []
    skipped = 0

    for order in assembly_orders:
        status = order.get("status")
        if status not in ("confirmed", "assembled"):
            skipped += 1
            continue

        item_id = str(
            order.get("composite_item_id")
            or order.get("item_id")
            or ""
        )
        cf_item_type = item_type_map.get(item_id)

        record = make_record(order)

        if cf_item_type == "Finished Product / Sales Product":
            if status == "confirmed":
                finished_in_production.append(record)
            else:
                finished_completed.append(record)
        elif cf_item_type == "Subassembly":
            if status == "confirmed":
                subassemblies_in_production.append(record)
            else:
                subassemblies_completed.append(record)
        else:
            skipped += 1

    if skipped:
        print(f"  Skipped {skipped} orders (wrong status or unknown item type)")

    return finished_in_production, finished_completed, subassemblies_in_production, subassemblies_completed


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

    print("Fetching items...")
    items = fetch_all_pages(
        ZOHO_ITEMS_URL,
        headers,
        {"organization_id": org_id},
        "items",
    )
    item_type_map = build_item_type_map(items)
    print(f"  Built item type map with {len(item_type_map)} entries")

    now = datetime.now(timezone.utc)
    month_str = now.strftime("%Y-%m")
    date_start = now.strftime("%Y-%m-01")
    last_day = calendar.monthrange(now.year, now.month)[1]
    date_end = now.strftime(f"%Y-%m-{last_day:02d}")

    print(f"Fetching assembly orders for {month_str} ({date_start} to {date_end})...")
    assembly_orders = fetch_all_pages(
        ZOHO_ASSEMBLY_URL,
        headers,
        {
            "organization_id": org_id,
            "date_start": date_start,
            "date_end": date_end,
        },
        "assembly_orders",
    )

    fp_ip, fp_done, sa_ip, sa_done = classify_orders(assembly_orders, item_type_map)

    output = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "month": month_str,
        "finished_products": {
            "in_production": fp_ip,
            "completed": fp_done,
        },
        "subassemblies": {
            "in_production": sa_ip,
            "completed": sa_done,
        },
    }

    os.makedirs("data", exist_ok=True)

    month_file = f"data/{month_str}.json"
    with open(month_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {month_file}")

    with open("data/latest.json", "w") as f:
        json.dump(output, f, indent=2)
    print("Wrote data/latest.json")

    months = update_index("data/index.json", month_str)
    print(f"Wrote data/index.json - available months: {months}")


if __name__ == "__main__":
    main()
