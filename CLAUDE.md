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
Assembly status mapping:
  "confirmed"  → In Production
  "assembled"  → Assembly Completed

## JSON schema
See data/latest.json for shape. One file per month: data/YYYY-MM.json
latest.json always mirrors current month for default dashboard load.
index.json contains array of available month strings for navigation.

## GitHub Secrets required
ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_ORG_ID

## API endpoints
Items:      GET https://www.zohoapis.com/inventory/v1/items
Assemblies: GET https://www.zohoapis.com/inventory/v1/compositeitems/assemblyorders
Both paginate at 200 per page — always fetch all pages before processing.

## Constraints
- No JS frameworks, no CSS frameworks, no external dependencies in index.html
- No build step — index.html must be servable as-is by GitHub Pages
- Do not manually edit files in the data/ directory
- Pagination must be handled on both API endpoints
