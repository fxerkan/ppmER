#!/usr/bin/env python3
"""
Fix dashboard parameters for PPM dashboards.

The PUT /api/dashboard/:id call must include BOTH 'parameters' AND 'dashcards'
(with parameter_mappings) in the same payload.

This script:
1. Gets all PPM dashboards (excluding PPM Home which has no filters)
2. For each dashcard:
   - Preserves existing parameter_mappings if already set
   - Otherwise inspects the card's template-tags and auto-builds mappings
3. Re-sends PUT with standard parameters + updated dashcards

Non-destructive: existing parameter_mappings are never erased.
"""

import json
import urllib.request
import urllib.error
import time

MB_URL = "http://localhost:3000"
ADMIN_EMAIL = "admin@jppm.local"
ADMIN_PASSWORD = "Jppm@min123"


def api(method, path, data=None, session_id=None):
    url = MB_URL + "/api" + path
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["X-Metabase-Session"] = session_id
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print("WARN: %s %s -> %s: %s" % (method, path, e.code, e.read().decode()[:300]))
        return None


def get_session():
    r = api("POST", "/session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    return r["id"]


STANDARD_PARAMS = [
    {
        "id": "date_param",
        "name": "Date Range",
        "type": "date/all-options",
        "slug": "date_range",
        "sectionId": "date",
    },
    {
        "id": "project_param",
        "name": "Project",
        "type": "string/=",
        "slug": "project_key",
        "sectionId": "string",
    },
    {
        "id": "team_param",
        "name": "Team",
        "type": "string/=",
        "slug": "team",
        "sectionId": "string",
    },
    {
        "id": "user_param",
        "name": "User",
        "type": "string/=",
        "slug": "user_name",
        "sectionId": "string",
    },
    {
        "id": "issuetype_param",
        "name": "Issue Type",
        "type": "string/=",
        "slug": "issue_type",
        "sectionId": "string",
    },
]

# Map from template-tag name -> (parameter_id, target_type)
# target_type is "dimension" for date tags, "variable" for text tags
TAG_TO_PARAM = {
    "date_range":  ("date_param",      "dimension"),
    "project_key": ("project_param",   "variable"),
    "team":        ("team_param",      "variable"),
    "user_name":   ("user_param",      "variable"),
    "issue_type":  ("issuetype_param", "variable"),
}


def extract_template_tags(card_detail):
    """
    Extract template-tags from a card's dataset_query.

    Metabase stores queries in two formats:
    - Legacy native format:  dataset_query.native.template-tags
    - MBQL pMBQL format:     dataset_query.stages[0].template-tags

    Returns a dict of {tag_name: tag_def}.
    """
    dq = card_detail.get("dataset_query", {})

    # Try legacy native format first
    native = dq.get("native", {})
    if isinstance(native, dict) and native.get("template-tags"):
        tags = native["template-tags"]
        if isinstance(tags, dict) and tags:
            return tags

    # Try pMBQL (newer Metabase format): stages[0]["template-tags"]
    stages = dq.get("stages", [])
    if stages and isinstance(stages[0], dict):
        tags = stages[0].get("template-tags", {})
        if isinstance(tags, dict) and tags:
            return tags

    return {}


def build_mappings_from_tags(card_id, card_detail):
    """Inspect a card's template-tags and return parameter_mappings list."""
    mappings = []
    if not card_detail:
        return mappings

    tags = extract_template_tags(card_detail)

    for tag_name, tag_def in tags.items():
        if tag_name in TAG_TO_PARAM:
            param_id, target_type = TAG_TO_PARAM[tag_name]
            mappings.append(
                {
                    "parameter_id": param_id,
                    "card_id": card_id,
                    "target": [target_type, ["template-tag", tag_name]],
                }
            )

    return mappings


def fix_dashboard(session_id, dash_id, dash_name):
    detail = api("GET", "/dashboard/%d" % dash_id, session_id=session_id)
    if not detail:
        print("  SKIP %s (id=%d): could not fetch detail" % (dash_name, dash_id))
        return False

    current_cards = detail.get("dashcards", [])
    current_tabs  = detail.get("tabs", [])
    current_params = detail.get("parameters", [])

    # Track which parameter IDs are wired up
    used_param_ids = set()

    # Collect existing wired param IDs from current dashcards
    for dc in current_cards:
        for pm in dc.get("parameter_mappings", []):
            used_param_ids.add(pm.get("parameter_id"))

    updated_cards = []
    new_mappings_added = 0

    for dc in current_cards:
        card_id = dc.get("card_id")
        existing_mappings = dc.get("parameter_mappings", [])
        updated_dc = dict(dc)

        if existing_mappings:
            # Non-destructive: keep existing mappings unchanged
            updated_dc["parameter_mappings"] = existing_mappings
        elif card_id:
            # Try to auto-discover from card's template-tags
            card = api("GET", "/card/%d" % card_id, session_id=session_id)
            new_mappings = build_mappings_from_tags(card_id, card)
            updated_dc["parameter_mappings"] = new_mappings
            if new_mappings:
                new_mappings_added += len(new_mappings)
                for m in new_mappings:
                    used_param_ids.add(m["parameter_id"])
            time.sleep(0.1)

        updated_cards.append(updated_dc)

    # Active params = those wired to at least one card; fall back to all standard
    # params so the filter bar still appears even for dashboards whose SQL has no tags.
    active_params = [p for p in STANDARD_PARAMS if p["id"] in used_param_ids]
    if not active_params:
        print(
            "  NOTE %s (id=%d): no template-tag matches found — applying all standard "
            "params (filter bar appears but cards are unconnected; add {{tags}} to SQL to wire up)"
            % (dash_name, dash_id)
        )
        active_params = STANDARD_PARAMS

    payload = {
        "parameters": active_params,
        "dashcards": updated_cards,
    }
    if current_tabs:
        payload["tabs"] = current_tabs

    result = api("PUT", "/dashboard/%d" % dash_id, payload, session_id=session_id)

    if result is not None:
        total_mappings = sum(len(dc.get("parameter_mappings", [])) for dc in updated_cards)
        print(
            "  FIXED %s (id=%d): %d params, %d cards, %d total mappings (%d newly added)"
            % (dash_name, dash_id, len(active_params), len(updated_cards), total_mappings, new_mappings_added)
        )
        return True
    else:
        print("  FAIL  %s (id=%d): PUT returned None" % (dash_name, dash_id))
        return False


def verify(session_id, dash_ids):
    print("\n=== Verification ===")
    all_ok = True
    for did in dash_ids:
        detail = api("GET", "/dashboard/%d" % did, session_id=session_id)
        if detail:
            params = detail.get("parameters", [])
            cards  = detail.get("dashcards", [])
            total_mappings = sum(len(dc.get("parameter_mappings", [])) for dc in cards)
            ok = len(params) > 0
            status = "OK" if ok else "FAIL"
            print(
                "  [%s] id=%d  params=%d  cards=%d  mappings=%d  %s"
                % (status, did, len(params), len(cards), total_mappings, detail["name"])
            )
            if not ok:
                all_ok = False
    return all_ok


def main():
    print("=== PPM Dashboard Parameter Fixer ===")
    session_id = get_session()
    print("Authenticated.")

    # Get all dashboards
    all_dashes = api("GET", "/dashboard", session_id=session_id) or []
    # Target PPM dashboards, excluding PPM Home (no filters needed there)
    ppm_dashes = [
        d for d in all_dashes
        if d.get("name", "").startswith("PPM") and d.get("name") != "PPM Home"
    ]

    if not ppm_dashes:
        print("No PPM dashboards found (excluding PPM Home).")
        return

    print("\nFound %d PPM dashboards to process:" % len(ppm_dashes))
    for d in ppm_dashes:
        print("  id=%d  %s" % (d["id"], d["name"]))

    print()
    fixed = 0
    for d in ppm_dashes:
        ok = fix_dashboard(session_id, d["id"], d["name"])
        if ok:
            fixed += 1
        time.sleep(0.3)

    all_ok = verify(session_id, [d["id"] for d in ppm_dashes])

    print("\nDone. Fixed %d / %d dashboards." % (fixed, len(ppm_dashes)))
    if all_ok:
        print("All PPM dashboards now have parameters set.")
    else:
        print("WARNING: Some dashboards still have parameters=0. Check WARN output above.")


if __name__ == "__main__":
    main()
