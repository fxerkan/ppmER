#!/usr/bin/env python3
"""Import PPM content from metabase/exports/ back into Metabase.

Reads the JSON files produced by export_metabase.py and upserts them
into Metabase via the API. Safe to re-run (upsert by name).

ID remapping: since card IDs change on a fresh instance, dashcard
references are rewritten using an old_id → new_id map built during
the card import phase.

Usage:
    python3 metabase/import_metabase.py           # import all
    python3 metabase/import_metabase.py --dry-run # preview only
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

MB_URL = os.getenv("MB_URL", "http://localhost:3000")
ADMIN_EMAIL = os.getenv("MB_ADMIN_EMAIL", "admin@jppm.local")
ADMIN_PASSWORD = os.getenv("MB_ADMIN_PASSWORD", "Jppm@min123")
EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")
DRY_RUN = "--dry-run" in sys.argv


def api(method, path, data=None, session_id=None):
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["X-Metabase-Session"] = session_id
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{MB_URL}/api{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:300]
        print(f"  WARN: {method} {path} → {e.code}: {msg}")
        return None


def load(path):
    with open(path) as f:
        return json.load(f)


def find_by_name(items, name, name_key="name"):
    return next((i for i in items if i.get(name_key) == name), None)


# ── Session ───────────────────────────────────────────────────────────────────
print(f"Connecting to {MB_URL}...")
r = api("POST", "/session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
if not r or "id" not in r:
    print("FATAL: Auth failed")
    sys.exit(1)
session = r["id"]
print("Authenticated\n")

if DRY_RUN:
    print("DRY-RUN mode — no writes\n")

# ── Step 1: Collections ───────────────────────────────────────────────────────
print("=== Collections ===")
exported_collections = load(f"{EXPORTS_DIR}/collections.json")
existing_collections = api("GET", "/collection", session_id=session) or []

# old_collection_id → new_collection_id
col_id_map = {}

# Find or create root "PPM Insights"
root_export = next(c for c in exported_collections if c.get("parent_id") is None or c.get("name") == "PPM Insights")
existing_root = find_by_name(existing_collections, "PPM Insights")

if existing_root:
    new_root_id = existing_root["id"]
    print(f"  Found 'PPM Insights' (id={new_root_id})")
elif not DRY_RUN:
    r = api("POST", "/collection", {"name": "PPM Insights", "color": "#509EE3"}, session_id=session)
    new_root_id = r["id"]
    print(f"  Created 'PPM Insights' (id={new_root_id})")
else:
    new_root_id = 999  # placeholder

col_id_map[root_export["id"]] = new_root_id

# Re-fetch to include newly created root
existing_collections = api("GET", "/collection", session_id=session) or []

# Create sub-collections
for col in exported_collections:
    if col["id"] == root_export["id"]:
        continue
    name = col["name"]
    existing = find_by_name(existing_collections, name)
    if existing:
        col_id_map[col["id"]] = existing["id"]
        print(f"  Found sub-collection '{name}' (id={existing['id']})")
    elif not DRY_RUN:
        r = api("POST", "/collection", {
            "name": name,
            "color": col.get("color", "#509EE3"),
            "parent_id": new_root_id,
        }, session_id=session)
        if r:
            col_id_map[col["id"]] = r["id"]
            print(f"  Created sub-collection '{name}' (id={r['id']})")
        time.sleep(0.2)
    else:
        col_id_map[col["id"]] = 9000 + col["id"]  # placeholder

# ── Step 2: Cards (models first, then questions) ──────────────────────────────
print("\n=== Cards ===")
card_index = load(f"{EXPORTS_DIR}/cards/_index.json")
existing_cards_list = api("GET", "/card", session_id=session) or []
existing_by_name = {c["name"]: c["id"] for c in existing_cards_list}

# old_card_id → new_card_id (for dashcard remapping)
card_id_map = {}

# Import models before regular questions (questions may depend on models)
def card_sort_key(entry):
    return 0 if entry.get("type") == "model" else 1

for entry in sorted(card_index, key=card_sort_key):
    card_file = f"{EXPORTS_DIR}/{entry['file']}"
    card = load(card_file)
    name = card["name"]
    old_id = card["id"]

    # Remap collection_id
    old_col_id = card.get("collection_id")
    new_col_id = col_id_map.get(old_col_id) if old_col_id else None

    # Strip server-only fields
    payload = {
        "name": name,
        "display": card.get("display", "table"),
        "dataset_query": card.get("dataset_query", {}),
        "visualization_settings": card.get("visualization_settings", {}),
        "collection_id": new_col_id,
        "description": card.get("description"),
    }
    if card.get("type") == "model":
        payload["type"] = "model"

    if name in existing_by_name:
        existing_id = existing_by_name[name]
        card_id_map[old_id] = existing_id
        if not DRY_RUN:
            api("PUT", f"/card/{existing_id}", payload, session_id=session)
        print(f"  Updated '{name}' (old={old_id} → new={existing_id})")
    elif not DRY_RUN:
        r = api("POST", "/card", payload, session_id=session)
        if r and "id" in r:
            card_id_map[old_id] = r["id"]
            print(f"  Created '{name}' (old={old_id} → new={r['id']})")
        time.sleep(0.2)
    else:
        card_id_map[old_id] = 8000 + old_id  # placeholder

print(f"\n  {len(card_id_map)} cards processed")

# ── Step 3: Dashboards ────────────────────────────────────────────────────────
print("\n=== Dashboards ===")
dash_index = load(f"{EXPORTS_DIR}/dashboards/_index.json")
all_existing_dashes = api("GET", "/dashboard", session_id=session) or []
if isinstance(all_existing_dashes, dict):
    all_existing_dashes = all_existing_dashes.get("data", [])
existing_dash_by_name = {d["name"]: d["id"] for d in all_existing_dashes}


def remap_dashcards(dashcards):
    """Rewrite card_id and parameter_mappings.card_id using card_id_map."""
    updated = []
    neg_id = [-1]

    def new_neg():
        v = neg_id[0]
        neg_id[0] -= 1
        return v

    for dc in dashcards:
        dc2 = dict(dc)
        old_cid = dc.get("card_id")
        if old_cid is not None:
            dc2["card_id"] = card_id_map.get(old_cid, old_cid)
        dc2["id"] = new_neg()  # always use a fresh negative ID

        # Remap parameter_mappings card_id
        new_pm = []
        for pm in dc.get("parameter_mappings", []):
            pm2 = dict(pm)
            if "card_id" in pm2:
                pm2["card_id"] = card_id_map.get(pm2["card_id"], pm2["card_id"])
            new_pm.append(pm2)
        dc2["parameter_mappings"] = new_pm

        # Strip server-only keys
        for k in ("entity_id", "created_at", "updated_at", "dashboard_id"):
            dc2.pop(k, None)

        updated.append(dc2)
    return updated


for entry in dash_index:
    dash_file = f"{EXPORTS_DIR}/{entry['file']}"
    dash = load(dash_file)
    name = dash["name"]

    # Strip tabs so we can re-attach; remap dashcards
    tabs = dash.get("tabs", [])
    # Assign fresh negative IDs to tabs and update dashcard tab references
    tab_id_map = {}
    new_tabs = []
    for i, tab in enumerate(tabs):
        new_tid = -(i + 1)
        tab_id_map[tab["id"]] = new_tid
        new_tabs.append({"id": new_tid, "name": tab["name"]})

    dashcards = remap_dashcards(dash.get("dashcards", []))
    for dc in dashcards:
        if "dashboard_tab_id" in dc and dc["dashboard_tab_id"] is not None:
            dc["dashboard_tab_id"] = tab_id_map.get(dc["dashboard_tab_id"], dc["dashboard_tab_id"])

    payload = {
        "name": name,
        "description": dash.get("description", ""),
        "parameters": dash.get("parameters", []),
        "dashcards": dashcards,
        "tabs": new_tabs,
        "width": "full",
    }

    if name in existing_dash_by_name:
        did = existing_dash_by_name[name]
        if not DRY_RUN:
            api("PUT", f"/dashboard/{did}", payload, session_id=session)
        print(f"  Updated '{name}' (id={did}, {len(dashcards)} cards)")
    elif not DRY_RUN:
        r = api("POST", "/dashboard", {"name": name, "description": payload["description"]}, session_id=session)
        if r and "id" in r:
            did = r["id"]
            api("PUT", f"/dashboard/{did}", payload, session_id=session)
            print(f"  Created '{name}' (id={did}, {len(dashcards)} cards)")
        time.sleep(0.3)
    else:
        print(f"  [dry-run] Would upsert '{name}' ({len(dashcards)} cards)")

    time.sleep(0.2)

print("\nImport complete.")
