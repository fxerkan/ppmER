#!/usr/bin/env python3
"""Export all PPM content from Metabase API to metabase/exports/ as JSON files."""

import json
import os
import sys
import time
import urllib.request
import urllib.error

MB_URL = os.getenv("MB_URL", "http://localhost:3000")
ADMIN_EMAIL = os.getenv("MB_ADMIN_EMAIL", "admin@jppm.local")
ADMIN_PASSWORD = os.getenv("MB_ADMIN_PASSWORD", "Jppm@min123")
OUT_DIR = os.path.join(os.path.dirname(__file__), "exports")


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
        print(f"  WARN: {method} {path} -> {e.code}: {e.read().decode()[:200]}")
        return None


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def slug(name):
    return name.lower().replace(" ", "_").replace("/", "-").replace("&", "and")


def main():
    print(f"Connecting to {MB_URL}...")
    r = api("POST", "/session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if not r or "id" not in r:
        print("FATAL: Auth failed")
        sys.exit(1)
    session = r["id"]
    print("Authenticated\n")

    # ── Collections ──────────────────────────────────────────────────────────
    print("Exporting collections...")
    all_collections = api("GET", "/collection", session_id=session) or []
    # Find root "PPM Insights" collection then walk all children
    ppm_root = next((c for c in all_collections if c.get("name") == "PPM Insights"), None)
    if not ppm_root:
        print("FATAL: 'PPM Insights' collection not found")
        sys.exit(1)

    root_id = ppm_root["id"]
    ppm_collection_ids = {root_id} | {c["id"] for c in all_collections if c.get("parent_id") == root_id}
    ppm_collections = [c for c in all_collections if c["id"] in ppm_collection_ids]
    save(f"{OUT_DIR}/collections.json", ppm_collections)
    print(f"  {len(ppm_collections)} PPM collections saved (root={root_id})")

    # ── Cards (questions + models) ────────────────────────────────────────────
    print("\nExporting cards...")
    all_cards = api("GET", "/card", session_id=session) or []
    # Filter to PPM collections only
    ppm_cards = [c for c in all_cards if c.get("collection_id") in ppm_collection_ids]

    os.makedirs(f"{OUT_DIR}/cards", exist_ok=True)
    card_index = []
    for card in ppm_cards:
        # Fetch full detail (includes dataset_query with SQL)
        detail = api("GET", f"/card/{card['id']}", session_id=session)
        if not detail:
            continue
        filename = f"{detail['id']}_{slug(detail['name'])[:50]}.json"
        save(f"{OUT_DIR}/cards/{filename}", detail)
        card_index.append({
            "id": detail["id"],
            "name": detail["name"],
            "display": detail.get("display"),
            "type": detail.get("type"),
            "collection_id": detail.get("collection_id"),
            "file": f"cards/{filename}",
        })
        time.sleep(0.05)

    save(f"{OUT_DIR}/cards/_index.json", card_index)
    print(f"  {len(card_index)} cards saved")

    # ── Dashboards ────────────────────────────────────────────────────────────
    print("\nExporting dashboards...")
    all_dashboards = api("GET", "/dashboard", session_id=session) or []
    # Metabase returns list or {data: [...]}
    if isinstance(all_dashboards, dict):
        all_dashboards = all_dashboards.get("data", [])

    ppm_dashboards = [d for d in all_dashboards if d.get("name", "").startswith("PPM")]

    os.makedirs(f"{OUT_DIR}/dashboards", exist_ok=True)
    dash_index = []
    for dash in ppm_dashboards:
        # Fetch full detail (includes dashcards, parameters, tabs)
        detail = api("GET", f"/dashboard/{dash['id']}", session_id=session)
        if not detail:
            continue
        filename = f"{detail['id']}_{slug(detail['name'])[:50]}.json"
        save(f"{OUT_DIR}/dashboards/{filename}", detail)
        dash_index.append({
            "id": detail["id"],
            "name": detail["name"],
            "description": detail.get("description", ""),
            "tabs": [t["name"] for t in detail.get("tabs", [])],
            "parameters": [p["name"] for p in detail.get("parameters", [])],
            "card_count": len(detail.get("dashcards", [])),
            "file": f"dashboards/{filename}",
        })
        time.sleep(0.1)

    save(f"{OUT_DIR}/dashboards/_index.json", dash_index)
    print(f"  {len(dash_index)} dashboards saved")

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = {
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metabase_url": MB_URL,
        "collections": len(ppm_collections),
        "cards": len(card_index),
        "dashboards": len(dash_index),
        "dashboards_list": [{"id": d["id"], "name": d["name"], "url": f"{MB_URL}/dashboard/{d['id']}"} for d in dash_index],
    }
    save(f"{OUT_DIR}/manifest.json", summary)

    print(f"\nExport complete → {OUT_DIR}/")
    print(f"  Collections : {summary['collections']}")
    print(f"  Cards       : {summary['cards']}")
    print(f"  Dashboards  : {summary['dashboards']}")
    for d in dash_index:
        print(f"    [{d['id']}] {d['name']} ({d['card_count']} cards, tabs: {d['tabs']})")


if __name__ == "__main__":
    main()
