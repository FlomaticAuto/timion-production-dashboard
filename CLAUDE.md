# Production Dashboard

## Purpose
Static HTML dashboard showing Zoho Inventory assembly orders for the month,
split by type (Finished Product / Subassembly) and status (In Production /
Assembly Completed). Hosted on GitHub Pages. Data refreshed by GitHub Action.

## Repo structure
.github/workflows/sync.yml   — scheduled GitHub Action
scripts/fetch_zoho.py        — Zoho API fetch and JSON writer
data/YYYY-MM.json            — monthly data files (auto-generated, do not edit)
data/latest.json             — copy of current month file (auto-generated)
data/index.json              — list of available month strings (auto-generated)
index.html                   — dashboard (single file, no build step)
CLAUDE.md                    — this file

## Zoho field mapping
Custom field label: Inventory Type
Custom field API name: cf_item_type
Values: "Subassembly" | "Finished Product / Sales Product"
Bundle status mapping:
  "draft"     → In Production (Draft badge)
  "confirmed" → In Production (Confirmed badge)
  "bundled"   → Assembly Completed

## JSON schema
Each record: { assembly_number, item_name, quantity, date, status, production_staff, serial_numbers }
Top-level: { generated_at, month, finished_products: { in_production: [], completed: [] }, subassemblies: { in_production: [], completed: [] } }
See data/latest.json for a live example.
latest.json always mirrors current month for default dashboard load.
index.json contains array of available month strings for navigation.

## GitHub Secrets required
ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_ORG_ID

## API endpoints
Composite items list: GET https://www.zohoapis.com/inventory/v1/compositeitems
Item detail:          GET https://www.zohoapis.com/inventory/v1/compositeitems/{id}
Bundles by item:      GET https://www.zohoapis.com/inventory/v1/bundles?composite_item_id={id}
Bundle detail:        GET https://www.zohoapis.com/inventory/v1/bundles/{bundle_id}
All endpoints paginate at 200 per page — always fetch all pages before processing.

## Script flow (scripts/fetch_zoho.py)
1. GET /compositeitems → ~430 items (response key: composite_items)
2. Item type cache (data/item_type_cache.json): first run of each day fetches GET /compositeitems/{id}
   for all items; subsequent runs reuse cache (0 extra API calls)
3. Filter to PRODUCTION_TYPES → ~246 items
4. GET /bundles?composite_item_id={id} per item → filter to target month by date prefix
5. GET /bundles/{bundle_id} per bundle → extract cf_production_staff, finished_product_serial_numbers
6. Classify: status "bundled" → completed; "draft"/"confirmed" → in production
7. Write data/YYYY-MM.json; write data/latest.json only when running for current month

## Constraints
- No JS frameworks, no CSS frameworks, no external dependencies in index.html
- No build step — index.html must be servable as-is by GitHub Pages
- Do not manually edit files in the data/ directory
- Pagination must be handled on all API endpoints
