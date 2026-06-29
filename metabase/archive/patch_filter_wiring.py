"""
patch_filter_wiring.py
======================
Fixes 6 Metabase dashboards (20, 23, 24, 25, 26, 27) that have parameters
defined but 0 parameter_mappings because their SQL cards lack template tags.

Dashboards 21 (Timesheet) and 22 (Missing Effort) are already wired — NOT touched.

Strategy per dashboard type:
  - Financial dashboards (20, 23, 24): tables have `period` (text) column.
    Change date_param to string/= mapped to period_filter template tag.
    Add project_key, team, user_name, issue_type text tags where columns exist.
  - Leadership (25): core.dim_projects — add project_key text tag.
  - Ops Quality (26): core tables with no clear common filter column — add
    project_key where project_key column is present.
  - Ops Master Data (27): core.dim_projects / dim_users / fact_worklogs —
    add project_key tag where applicable.

The cards use Metabase MBQL v2 format:
  dataset_query.stages[0].native  -> SQL string
  dataset_query.stages[0].template-tags -> tag dict

Parameter mapping target formats:
  text/variable tag -> ["variable", ["template-tag", "<name>"]]
  dimension tag     -> ["dimension", ["template-tag", "<name>"]]
"""

import json
import time
import urllib.request
import urllib.error

MB_URL = "http://localhost:3000"
CREDS = {"username": "admin@jppm.local", "password": "Jppm@min123"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(method, path, data=None, session_id=None):
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["X-Metabase-Session"] = session_id
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"{MB_URL}/api{path}", data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  WARN: {method} {path} -> {e.code}: {e.read().decode()[:300]}")
        return None


def get_card_sql_and_tags(card):
    """Return (sql, tags_dict) from the MBQL v2 stages-based card."""
    dq = card.get("dataset_query", {})
    stages = dq.get("stages", [])
    if not stages:
        return "", {}
    stage0 = stages[0]
    return stage0.get("native", ""), dict(stage0.get("template-tags", {}))


def build_updated_dataset_query(card, new_sql, new_tags):
    """Return a dataset_query dict with updated SQL and template-tags."""
    dq = dict(card.get("dataset_query", {}))
    stages = list(dq.get("stages", [{}]))
    stage0 = dict(stages[0])
    stage0["native"] = new_sql
    stage0["template-tags"] = new_tags
    stages[0] = stage0
    dq["stages"] = stages
    return dq


def add_optional_where_clause(sql, condition):
    """
    Insert an optional Metabase filter clause into existing SQL.

    Rules:
      - If SQL already has WHERE, append ' [[AND <condition>]]' before
        ORDER BY / GROUP BY / LIMIT, or at end.
      - If no WHERE, add 'WHERE 1=1 [[AND <condition>]]' similarly.
      - condition should NOT include the surrounding [[ ]]; caller passes
        the inner part like 'period = {{period_filter}}'.
    """
    wrapped = f"[[AND {condition}]]"
    sql = sql.strip().rstrip(";")

    # Check whether condition is already present (idempotent)
    tag_name = condition.split("{{")[1].split("}}")[0] if "{{" in condition else ""
    if tag_name and f"{{{{{tag_name}}}}}" in sql:
        return sql  # already present

    upper = sql.upper()
    has_where = "WHERE" in upper

    # Find the right insertion point (before ORDER BY, GROUP BY, LIMIT, HAVING)
    insert_keywords = ["ORDER BY", "GROUP BY", "LIMIT", "HAVING"]
    insert_pos = None
    for kw in insert_keywords:
        idx = upper.rfind(kw)
        if idx != -1:
            if insert_pos is None or idx < insert_pos:
                insert_pos = idx

    if has_where:
        clause = f"\n  {wrapped}"
    else:
        clause = f"\nWHERE 1=1\n  {wrapped}"

    if insert_pos is not None:
        return sql[:insert_pos] + clause + "\n" + sql[insert_pos:]
    else:
        return sql + clause


def text_tag(name, display_name, uid):
    return {
        "type": "text",
        "id": uid,
        "name": name,
        "display-name": display_name,
        "required": False,
    }


# ---------------------------------------------------------------------------
# Template tag definitions (stable UUIDs so re-runs are idempotent)
# ---------------------------------------------------------------------------

TAG_DEFS = {
    "period_filter": text_tag(
        "period_filter", "Period", "33333333-3333-3333-3333-333333333333"
    ),
    "project_key": text_tag(
        "project_key", "Project", "44444444-4444-4444-4444-444444444444"
    ),
    "team": text_tag(
        "team", "Team", "55555555-5555-5555-5555-555555555555"
    ),
    "user_name": text_tag(
        "user_name", "User", "66666666-6666-6666-6666-666666666666"
    ),
    "issue_type": text_tag(
        "issue_type", "Issue Type", "77777777-7777-7777-7777-777777777777"
    ),
}

# ---------------------------------------------------------------------------
# Dashboard parameter sets
# ---------------------------------------------------------------------------

# For financial dashboards: the "Date Range" param becomes string/= for period
PARAMS_FINANCIAL = [
    {
        "id": "date_param",
        "name": "Period",
        "type": "string/=",
        "slug": "period_filter",
        "sectionId": "string",
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

# For core-table dashboards: keep date_param as date/all-options (no date col to map)
# and add project_key / team text filters
PARAMS_CORE = [
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

# Mapping from parameter id to (tag_name, target_type)
PARAM_TAG_MAP = {
    # financial dashboards: date_param maps to period_filter text tag
    "date_param_financial": ("period_filter", "variable"),
    "project_param": ("project_key", "variable"),
    "team_param": ("team", "variable"),
    "user_param": ("user_name", "variable"),
    "issuetype_param": ("issue_type", "variable"),
}

# ---------------------------------------------------------------------------
# Per-card SQL patching rules
#
# For each card we define which template tags to add and what SQL condition
# to append. Logic is driven by inspecting column names in the SQL.
# ---------------------------------------------------------------------------

def detect_columns_in_sql(sql):
    """
    Return a set of filterable column names for the given SQL.

    Detection combines two strategies:
    1. Literal column name appears in the SQL text (covers SELECT-list and WHERE).
    2. Well-known table name appears — implicitly grants all columns of that table,
       because aggregate/scalar KPIs omit individual column names from their SQL
       even though the underlying table has those columns.
    """
    lower = sql.lower()
    candidates = [
        "period", "project_key", "project_name", "team", "tribe",
        "author_team", "user_name", "author_name", "display_name",
        "issue_type", "issue_type_name", "category", "it_domain",
        "trx_date", "customer",
    ]
    found = {c for c in candidates if c in lower}

    # Table-based column inference
    # mart.fact_financial_dashboard_2026 contains: period, project_name,
    #   customer, it_domain, tribe, team (via author_team), category
    if "fact_financial_dashboard_2026" in lower:
        found.update(["period", "project_name", "customer", "it_domain", "tribe"])

    # mart.fact_distributed_efforts_2026 contains the same schema
    if "fact_distributed_efforts_2026" in lower:
        found.update(["period", "project_name", "customer", "it_domain", "tribe"])

    # mart.rpt_missing_effort: trx_date, author_name, author_team, issue_type_name
    if "rpt_missing_effort" in lower:
        found.update(["trx_date", "author_name", "author_team", "issue_type_name"])

    # core.dim_projects: project_key, project_name, it_domain
    if "dim_projects" in lower:
        found.update(["project_key", "project_name", "it_domain"])

    # core.dim_users: display_name, team
    if "dim_users" in lower:
        found.update(["display_name", "team"])

    # core.fact_worklogs: issue_type, issue_type_name
    if "fact_worklogs" in lower:
        found.update(["issue_type", "issue_type_name"])

    return found


def patch_financial_card(sql, tags):
    """
    Patch a card whose underlying table has a `period` text column.
    Adds period_filter, project_key, team, user_name, issue_type tags
    where the corresponding column appears in the SQL.
    Returns (new_sql, new_tags, added_tags_list).
    """
    tags = dict(tags)
    new_sql = sql
    cols = detect_columns_in_sql(sql)
    added = []

    # period filter — applies to most financial cards
    if "period_filter" not in tags and "period" in cols:
        new_sql = add_optional_where_clause(new_sql, "period = {{period_filter}}")
        tags["period_filter"] = TAG_DEFS["period_filter"]
        added.append("period_filter")

    # project filter — either project_key or project_name column
    if "project_key" not in tags:
        if "project_key" in cols:
            new_sql = add_optional_where_clause(new_sql, "project_key = {{project_key}}")
            tags["project_key"] = TAG_DEFS["project_key"]
            added.append("project_key")
        elif "project_name" in cols:
            new_sql = add_optional_where_clause(new_sql, "project_name = {{project_key}}")
            tags["project_key"] = TAG_DEFS["project_key"]
            added.append("project_key")

    # team filter
    if "team" not in tags:
        if "team" in cols:
            new_sql = add_optional_where_clause(new_sql, "team = {{team}}")
            tags["team"] = TAG_DEFS["team"]
            added.append("team")
        elif "author_team" in cols:
            new_sql = add_optional_where_clause(new_sql, "author_team = {{team}}")
            tags["team"] = TAG_DEFS["team"]
            added.append("team")

    # user filter
    if "user_name" not in tags:
        if "user_name" in cols:
            new_sql = add_optional_where_clause(new_sql, "user_name = {{user_name}}")
            tags["user_name"] = TAG_DEFS["user_name"]
            added.append("user_name")
        elif "author_name" in cols:
            new_sql = add_optional_where_clause(new_sql, "author_name = {{user_name}}")
            tags["user_name"] = TAG_DEFS["user_name"]
            added.append("user_name")

    # issue_type filter
    if "issue_type" not in tags:
        if "issue_type_name" in cols:
            new_sql = add_optional_where_clause(new_sql, "issue_type_name = {{issue_type}}")
            tags["issue_type"] = TAG_DEFS["issue_type"]
            added.append("issue_type")
        elif "issue_type" in cols:
            new_sql = add_optional_where_clause(new_sql, "issue_type = {{issue_type}}")
            tags["issue_type"] = TAG_DEFS["issue_type"]
            added.append("issue_type")

    return new_sql, tags, added


def patch_core_card(sql, tags):
    """
    Patch a card querying core.* tables.
    Adds project_key, team, user_name, issue_type tags where columns exist.
    No period/date column to map (date_param is left unconnected for these).
    Returns (new_sql, new_tags, added_tags_list).
    """
    tags = dict(tags)
    new_sql = sql
    cols = detect_columns_in_sql(sql)
    added = []

    if "project_key" not in tags and "project_key" in cols:
        # Use table-qualified column if query uses alias 'p'
        if " p." in sql or "\np." in sql:
            new_sql = add_optional_where_clause(new_sql, "p.project_key = {{project_key}}")
        else:
            new_sql = add_optional_where_clause(new_sql, "project_key = {{project_key}}")
        tags["project_key"] = TAG_DEFS["project_key"]
        added.append("project_key")

    if "team" not in tags:
        if "team" in cols:
            new_sql = add_optional_where_clause(new_sql, "team = {{team}}")
            tags["team"] = TAG_DEFS["team"]
            added.append("team")

    if "user_name" not in tags:
        if "display_name" in cols:
            new_sql = add_optional_where_clause(new_sql, "display_name = {{user_name}}")
            tags["user_name"] = TAG_DEFS["user_name"]
            added.append("user_name")
        elif "author_name" in cols:
            new_sql = add_optional_where_clause(new_sql, "author_name = {{user_name}}")
            tags["user_name"] = TAG_DEFS["user_name"]
            added.append("user_name")

    if "issue_type" not in tags:
        if "issue_type_name" in cols:
            new_sql = add_optional_where_clause(new_sql, "issue_type_name = {{issue_type}}")
            tags["issue_type"] = TAG_DEFS["issue_type"]
            added.append("issue_type")
        elif "issue_type" in cols:
            new_sql = add_optional_where_clause(new_sql, "issue_type = {{issue_type}}")
            tags["issue_type"] = TAG_DEFS["issue_type"]
            added.append("issue_type")

    return new_sql, tags, added


# ---------------------------------------------------------------------------
# Build parameter_mappings for a dashcard based on which tags are present
# ---------------------------------------------------------------------------

def build_mappings(card_id, tags, dashboard_mode):
    """
    Build the parameter_mappings list for a dashcard.

    dashboard_mode: "financial" | "core"

    financial: date_param -> period_filter, project_param -> project_key, etc.
    core:      date_param is NOT mapped (no date tag on card),
               project_param -> project_key, etc.
    """
    mappings = []

    def add_map(param_id, tag_name, target_type="variable"):
        if tag_name in tags:
            target = (
                ["dimension", ["template-tag", tag_name]]
                if target_type == "dimension"
                else ["variable", ["template-tag", tag_name]]
            )
            mappings.append({
                "parameter_id": param_id,
                "card_id": card_id,
                "target": target,
            })

    if dashboard_mode == "financial":
        add_map("date_param", "period_filter")
    # core mode: date_param is left unmapped (no date column on these cards)

    add_map("project_param", "project_key")
    add_map("team_param", "team")
    add_map("user_param", "user_name")
    add_map("issuetype_param", "issue_type")

    return mappings


# ---------------------------------------------------------------------------
# Main patching logic
# ---------------------------------------------------------------------------

# Dashboard config: (dash_id, mode, params_list)
DASHBOARD_CONFIG = [
    (20, "financial", PARAMS_FINANCIAL),
    (23, "financial", PARAMS_FINANCIAL),
    (24, "financial", PARAMS_FINANCIAL),
    (25, "core",      PARAMS_CORE),
    (26, "core",      PARAMS_CORE),
    (27, "core",      PARAMS_CORE),
]


def patch_dashboard(session, dash_id, mode, params_list):
    print(f"\n--- Dashboard {dash_id} (mode={mode}) ---")

    dash = api("GET", f"/dashboard/{dash_id}", session_id=session)
    if not dash:
        print(f"  ERROR: dashboard {dash_id} not found")
        return

    # Must include tabs in the PUT payload — Metabase validates FK tab IDs
    tabs = dash.get("tabs", [])
    dashcards = dash.get("dashcards", [])
    updated_dashcards = []
    total_tags_added = 0

    for dc in dashcards:
        card_id = dc.get("card_id")
        if not card_id:
            # text/image card — keep as-is
            updated_dashcards.append(dc)
            continue

        card = api("GET", f"/card/{card_id}", session_id=session)
        if not card:
            updated_dashcards.append(dc)
            continue

        sql, tags = get_card_sql_and_tags(card)

        if not sql.strip():
            # Non-native card (MBQL GUI card) — skip SQL patching
            updated_dashcards.append(dc)
            continue

        # Patch SQL / tags
        if mode == "financial":
            new_sql, new_tags, added = patch_financial_card(sql, tags)
        else:
            new_sql, new_tags, added = patch_core_card(sql, tags)

        if added:
            # Push updated card
            updated_dq = build_updated_dataset_query(card, new_sql, new_tags)
            result = api(
                "PUT",
                f"/card/{card_id}",
                {"dataset_query": updated_dq},
                session_id=session,
            )
            if result:
                print(f"  Card {card_id} [{card.get('name')}]: added tags {added}")
                total_tags_added += len(added)
            else:
                print(f"  Card {card_id}: PUT failed — keeping original dc")
                updated_dashcards.append(dc)
                continue
            time.sleep(0.3)
            # Re-fetch to get updated tags (for mapping generation)
            fresh_card = api("GET", f"/card/{card_id}", session_id=session)
            if fresh_card:
                _, new_tags = get_card_sql_and_tags(fresh_card)
        else:
            print(f"  Card {card_id} [{card.get('name')}]: no changes needed")

        # Build mappings based on final tag set
        mappings = build_mappings(card_id, new_tags, mode)

        updated_dc = dict(dc)
        updated_dc["parameter_mappings"] = mappings
        updated_dashcards.append(updated_dc)

    # Update dashboard: replace params and all dashcards.
    # Including `tabs` is required — Metabase validates dashboard_tab_id FK.
    r = api(
        "PUT",
        f"/dashboard/{dash_id}",
        {
            "parameters": params_list,
            "tabs": tabs,
            "dashcards": updated_dashcards,
            "width": "full",
        },
        session_id=session,
    )
    if r is not None:
        total_mappings = sum(
            len(d.get("parameter_mappings", [])) for d in updated_dashcards
        )
        print(
            f"  Dashboard {dash_id} updated: "
            f"{len(params_list)} params, "
            f"{total_mappings} total mappings, "
            f"{total_tags_added} new tags added to cards"
        )
    else:
        print(f"  ERROR: Dashboard {dash_id} PUT failed")

    time.sleep(0.3)


def verify(session):
    print("\n=== Verification ===")
    print(f"{'DashID':<8} {'Name':<40} {'Params':>6} {'Mapped':>7}")
    print("-" * 65)
    for dash_id in [20, 21, 22, 23, 24, 25, 26, 27]:
        d = api("GET", f"/dashboard/{dash_id}", session_id=session)
        if not d:
            print(f"{dash_id:<8} NOT FOUND")
            continue
        params = len(d.get("parameters", []))
        mapped = sum(
            len(c.get("parameter_mappings", []))
            for c in d.get("dashcards", [])
        )
        note = " (skip)" if dash_id in (21, 22) else ""
        print(f"{dash_id:<8} {d.get('name','?')[:38]:<40} {params:>6} {mapped:>7}{note}")


def main():
    print("Authenticating...")
    resp = api("POST", "/session", CREDS)
    if not resp or "id" not in resp:
        print("ERROR: authentication failed")
        return
    session = resp["id"]
    print(f"Session: {session[:8]}...")

    for dash_id, mode, params_list in DASHBOARD_CONFIG:
        patch_dashboard(session, dash_id, mode, params_list)

    verify(session)
    print("\nDone.")


if __name__ == "__main__":
    main()
