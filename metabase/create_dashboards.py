#!/usr/bin/env python3
"""
PPM Metabase Dashboard Creator - Complete Rewrite
Fixes: filter panel mappings, date/all-options picker, clean card titles,
       broken SQL, collection name, model prefix, and adds PPM Home dashboard.
"""

import json
import time
import os
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:3000"
EMAIL = "admin@jppm.local"
PASSWORD = "Jppm@min123"
DB_ID = 2
SLEEP = 0.25
DEFINITIONS_FILE = os.path.join(os.path.dirname(__file__), "dashboards", "dashboard_definitions.json")

session = requests.Session()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def login():
    r = session.post(f"{BASE_URL}/api/session", json={"username": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    token = r.json()["id"]
    session.headers.update({"X-Metabase-Session": token})
    print("[AUTH] Logged in.")
    return token


# ---------------------------------------------------------------------------
# Raw API helper
# ---------------------------------------------------------------------------
def api(method, path, body=None):
    url = f"{BASE_URL}{path}"
    resp = session.request(method, url, json=body)
    if resp.status_code >= 400:
        print(f"  [WARN] {method} {path} -> {resp.status_code}: {resp.text[:400]}")
        return None
    time.sleep(SLEEP)
    try:
        return resp.json()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Step 1: Clean up existing PPM content
# ---------------------------------------------------------------------------
def cleanup():
    print("\n=== Cleanup: deleting existing PPM cards and dashboards ===")

    # Delete all non-archived cards
    cards = api("GET", "/api/card?f=all") or []
    for c in cards:
        cid = c.get("id")
        if cid:
            api("DELETE", f"/api/card/{cid}")
    print(f"  Deleted {len(cards)} cards.")

    # Archive dashboards
    dashes = api("GET", "/api/dashboard?f=all") or []
    for d in dashes:
        did = d.get("id")
        if did:
            api("DELETE", f"/api/dashboard/{did}")
    print(f"  Deleted {len(dashes)} dashboards.")

    # Find and delete PPM collections (children first)
    cols = api("GET", "/api/collection") or {}
    col_list = cols if isinstance(cols, list) else cols.get("data", [])
    ppm_ids = [c["id"] for c in col_list if c.get("name") in ("PPM", "PPM Insights")]
    # Delete sub-collections
    for c in col_list:
        if c.get("parent_id") in ppm_ids or c.get("location", "").strip("/").split("/")[0:1] == [str(p) for p in ppm_ids]:
            api("PUT", f"/api/collection/{c['id']}", {"archived": True})
    for pid in ppm_ids:
        api("PUT", f"/api/collection/{pid}", {"archived": True})
    print(f"  Archived {len(ppm_ids)} PPM collections.")


# ---------------------------------------------------------------------------
# Step 2: Sync schema and get field IDs
# ---------------------------------------------------------------------------
def sync_and_get_fields():
    print("\n=== Syncing schema and getting field IDs ===")
    api("POST", f"/api/database/{DB_ID}/sync_schema")
    time.sleep(3)

    meta = api("GET", f"/api/database/{DB_ID}/metadata")
    field_map = {}
    if meta:
        for t in meta.get("tables", []):
            schema = t.get("schema", "")
            tname = t.get("name", "")
            for f in t.get("fields", []):
                key = f"{schema}.{tname}.{f['name']}"
                field_map[key] = f["id"]
    print(f"  Got {len(field_map)} fields from metadata.")
    return field_map


# ---------------------------------------------------------------------------
# Step 3: Collections
# ---------------------------------------------------------------------------
def create_collection(name, parent_id=None):
    payload = {"name": name, "color": "#509EE3"}
    if parent_id:
        payload["parent_id"] = parent_id
    r = api("POST", "/api/collection", payload)
    if r and r.get("id"):
        print(f"  [COLLECTION] '{name}' -> id={r['id']}")
        return r["id"]
    # Fall back to finding existing
    cols = api("GET", "/api/collection") or {}
    col_list = cols if isinstance(cols, list) else cols.get("data", [])
    for c in col_list:
        if c.get("name") == name and not c.get("archived"):
            return c["id"]
    return None


# ---------------------------------------------------------------------------
# Template tags helpers
# ---------------------------------------------------------------------------
DATE_TAG_UUID = "11111111-1111-1111-1111-111111111111"
PROJ_TAG_UUID  = "22222222-70726f6a-1111-1111-111111111111"
TEAM_TAG_UUID  = "33333333-7465616d-1111-1111-111111111111"
USER_TAG_UUID  = "44444444-757365726-111-1111-111111111111"
TYPE_TAG_UUID  = "55555555-74797065-1111-1111-111111111111"
PERIOD_TAG_UUID = "66666666-706572696f-11-1111-111111111111"


def date_tag(field_id):
    """Dimension-type date tag for date/all-options filter."""
    return {
        "date_range": {
            "id": DATE_TAG_UUID,
            "name": "date_range",
            "display-name": "Date Range",
            "type": "dimension",
            "dimension": ["field", field_id, None],
            "widget-type": "date/all-options"
        }
    }


def text_tags(*names):
    """Text-type template tags."""
    uuids = {
        "project_key": PROJ_TAG_UUID,
        "team":        TEAM_TAG_UUID,
        "user_name":   USER_TAG_UUID,
        "issue_type":  TYPE_TAG_UUID,
        "period":      PERIOD_TAG_UUID,
    }
    tags = {}
    for n in names:
        tags[n] = {
            "id": uuids.get(n, f"aaaaaaaa-{n[:8].ljust(8,'0')}-1111-1111-111111111111"),
            "name": n,
            "display-name": n.replace("_", " ").title(),
            "type": "text",
            "required": False,
        }
    return tags


def merge_tags(*dicts):
    result = {}
    for d in dicts:
        result.update(d)
    return result


# ---------------------------------------------------------------------------
# Dashboard parameters
# ---------------------------------------------------------------------------
DATE_PARAM = {
    "id": "date_param",
    "name": "Date Range",
    "type": "date/all-options",
    "slug": "date_range",
    "sectionId": "date"
}
PROJECT_PARAM  = {"id": "project_param",   "name": "Project",    "type": "string/=", "slug": "project_key", "sectionId": "string"}
TEAM_PARAM     = {"id": "team_param",      "name": "Team",       "type": "string/=", "slug": "team",        "sectionId": "string"}
USER_PARAM     = {"id": "user_param",      "name": "User",       "type": "string/=", "slug": "user_name",   "sectionId": "string"}
ISSUETYPE_PARAM= {"id": "issuetype_param", "name": "Issue Type", "type": "string/=", "slug": "issue_type",  "sectionId": "string"}
PERIOD_PARAM   = {"id": "period_param",    "name": "Period",     "type": "string/=", "slug": "period",      "sectionId": "string"}

ALL_PARAMS = [DATE_PARAM, PROJECT_PARAM, TEAM_PARAM, USER_PARAM, ISSUETYPE_PARAM]


# ---------------------------------------------------------------------------
# parameter_mappings builder
# ---------------------------------------------------------------------------
def pm_date(card_id):
    return {
        "parameter_id": "date_param",
        "card_id": card_id,
        "target": ["dimension", ["template-tag", "date_range"]]
    }


def pm_text(param_id, tag_name, card_id):
    return {
        "parameter_id": param_id,
        "card_id": card_id,
        "target": ["variable", ["template-tag", tag_name]]
    }


def build_mappings(card_id, has_date=False, text_params=None):
    """
    text_params: list of (param_id, tag_name) tuples
    """
    mappings = []
    if has_date:
        mappings.append(pm_date(card_id))
    for pid, tname in (text_params or []):
        mappings.append(pm_text(pid, tname, card_id))
    return mappings


# ---------------------------------------------------------------------------
# Card creators
# ---------------------------------------------------------------------------
def create_card(name, collection_id, sql, tags, display="table", viz=None, card_type="question"):
    payload = {
        "name": name,
        "type": card_type,
        "dataset_query": {
            "type": "native",
            "native": {"query": sql, "template-tags": tags},
            "database": DB_ID
        },
        "display": display,
        "visualization_settings": viz or {},
        "collection_id": collection_id
    }
    r = api("POST", "/api/card", payload)
    if r and r.get("id"):
        print(f"    [CARD] '{name}' -> id={r['id']}")
        return r["id"]
    print(f"    [FAIL] Could not create card '{name}'")
    return None


def test_sql(sql):
    """Test SQL via /api/dataset and return (ok, message)."""
    r = api("POST", "/api/dataset", {
        "database": DB_ID,
        "type": "native",
        "native": {"query": sql}
    })
    if r is None:
        return False, "null response"
    if "error" in r:
        return False, r["error"]
    rows = r.get("data", {}).get("rows", [])
    return True, f"{len(rows)} rows"


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------
_dc_id = -1

def next_dc():
    global _dc_id
    _dc_id -= 1
    return _dc_id


def dashcard(card_id, tab_id, col, row, w=12, h=8, mappings=None):
    return {
        "id": next_dc(),
        "card_id": card_id,
        "dashboard_tab_id": tab_id,
        "col": col,
        "row": row,
        "size_x": w,
        "size_y": h,
        "parameter_mappings": mappings or [],
        "visualization_settings": {}
    }


def text_dashcard(content, tab_id, col, row, w=24, h=4):
    return {
        "id": next_dc(),
        "card_id": None,
        "dashboard_tab_id": tab_id,
        "col": col,
        "row": row,
        "size_x": w,
        "size_y": h,
        "parameter_mappings": [],
        "visualization_settings": {
            "virtual_card": {
                "display": "text",
                "dataset_query": {},
                "visualization_settings": {}
            },
            "text": content
        }
    }


def create_dashboard(name, collection_id, description=""):
    r = api("POST", "/api/dashboard", {
        "name": name,
        "description": description,
        "collection_id": collection_id
    })
    if r and r.get("id"):
        print(f"  [DASHBOARD] '{name}' -> id={r['id']}")
        return r["id"]
    return None


def put_dashboard(dash_id, tabs, cards, params):
    r = api("PUT", f"/api/dashboard/{dash_id}", {
        "tabs": tabs,
        "dashcards": cards,
        "parameters": params
    })
    if r:
        print(f"    Updated dashboard {dash_id}: {len(tabs)} tabs, {len(cards)} cards.")
    return r


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    login()
    os.makedirs(os.path.dirname(DEFINITIONS_FILE), exist_ok=True)

    cleanup()
    field_map = sync_and_get_fields()

    # Get field IDs for date columns
    trx_date_fid = field_map.get("mart.rpt_missing_effort.trx_date")
    fw_trx_date_fid = field_map.get("core.fact_worklogs.trx_date")
    print(f"  trx_date field IDs: rpt_missing_effort={trx_date_fid}, fact_worklogs={fw_trx_date_fid}")

    # Fall back: if field IDs not found, use workaround
    if not trx_date_fid:
        trx_date_fid = fw_trx_date_fid or 1

    definitions = {"collections": {}, "models": {}, "dashboards": {}}

    # -----------------------------------------------------------------------
    # Collections
    # -----------------------------------------------------------------------
    print("\n=== Creating Collections ===")
    ppm_id = create_collection("PPM Insights")
    definitions["collections"]["PPM Insights"] = ppm_id

    sub_names = ["Models", "Overview", "Timesheet", "Missing Effort",
                 "Distributed", "Financial", "Portfolio", "Data Quality", "Master Data"]
    sub = {}
    for name in sub_names:
        cid = create_collection(name, parent_id=ppm_id)
        sub[name] = cid

    # -----------------------------------------------------------------------
    # Metabase Models
    # -----------------------------------------------------------------------
    print("\n=== Creating Models ===")

    model_portfolio_sql = """
SELECT
    project_id, project_key, project_name, project_type,
    open_closed AS project_status,
    customer, it_domain, product, tribe, business_line,
    financial_code, completion_pct, total_hours_logged,
    total_issues, completed_issues, in_progress_issues, todo_issues,
    _etl_date
FROM core.dim_projects
"""
    mid_portfolio = create_card("Portfolio Model", sub["Models"], model_portfolio_sql,
                                tags={}, display="table", card_type="model")

    model_worklog_sql = """
SELECT
    worklog_id, trx_date,
    DATE_TRUNC('month', trx_date) AS month,
    period, project_key, project_name, issue_key,
    issue_type, issue_type_name, capex_opex, epic_name,
    author_name, author_team, author_unit, is_outsource_inhouse,
    time_spent_hours, time_spent_person_days, _etl_date
FROM core.fact_worklogs
"""
    mid_worklog = create_card("Worklog Analysis Model", sub["Models"], model_worklog_sql,
                              tags={}, display="table", card_type="model")

    model_dq_sql = """
SELECT
    author_name, author_team, period, trx_date,
    missing_effort_person_days, timesheet_entry_percentage,
    total_actual_effort_day, expected_effort_person_days
FROM mart.rpt_missing_effort
WHERE missing_effort_person_days > 0
"""
    mid_dq = create_card("Data Quality Model", sub["Models"], model_dq_sql,
                         tags={}, display="table", card_type="model")

    definitions["models"].update({"portfolio": mid_portfolio, "worklog": mid_worklog, "data_quality": mid_dq})

    # -----------------------------------------------------------------------
    # DASHBOARD 0 — PPM Home
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 0: PPM Home ===")
    dash0_id = create_dashboard("PPM Home", ppm_id,
                                "PPM Insights - Ana Sayfa. Tum PPM dashboard'larina erisim noktasi.")

    # We'll fill in real IDs after creating other dashboards
    # For now, create placeholder dashcards (no filters needed)
    dash0_tabs = [{"id": -1, "name": "Home"}]
    dash0_cards = [
        text_dashcard(
            "# PPM Insights\n\nProje ve Portfolyo Yonetimi veri platformuna hos geldiniz.\n\n"
            "Sol menuden veya asagidaki kartlardan ilgili dashboard'a gidin.",
            -1, 0, 0, w=24, h=3
        )
    ]
    # Link cards will be updated after we know dash IDs; add placeholders now
    link_cards_info = [
        ("Executive Overview", "Portfolyo ozeti, KPI'lar, finans"),
        ("Timesheet", "Gercek vs beklenen mesai"),
        ("Missing Effort", "Eksik timesheet analizi"),
        ("Distributed Effort", "Musteri/urun bazinda dagitilmis mesai"),
        ("Distribution Steps", "Dagitim adimlari detayi"),
        ("Strategic Portfolio", "Proje durumu ve tamamlanma"),
        ("Data Quality and Pipeline", "Veri kalitesi ve ETL durumu"),
        ("Master Data", "Referans veriler"),
    ]
    col_positions = [0, 8, 16, 0, 8, 16, 0, 8]
    row_positions = [3, 3, 3, 7, 7, 7, 11, 11]
    for i, (title, desc) in enumerate(link_cards_info):
        col = col_positions[i]
        row = row_positions[i]
        dash0_cards.append(
            text_dashcard(f"### {title}\n\n{desc}", -1, col, row, w=8, h=4)
        )

    if dash0_id:
        put_dashboard(dash0_id, dash0_tabs, dash0_cards, [])
    definitions["dashboards"]["home"] = dash0_id

    # -----------------------------------------------------------------------
    # DASHBOARD 1 — PPM - Executive - Overview
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 1: Executive Overview ===")
    dash1_id = create_dashboard("PPM - Executive - Overview", ppm_id,
                                "Executive summary of PPM portfolio performance and financials")
    definitions["dashboards"]["overview"] = dash1_id

    col1 = sub["Overview"]
    dt = date_tag(trx_date_fid)  # date dimension tag on rpt_missing_effort.trx_date

    # --- Tab 1: Overview ---
    # KPI cards using fact_financial_dashboard_2026 (no date column, use period text)
    kpi_total_effort = create_card(
        "Total Effort (Person Days)", col1,
        "SELECT ROUND(SUM(final_effort)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    kpi_distributed = create_card(
        "Distributed Effort", col1,
        "SELECT ROUND(SUM(total_distributed_all)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    kpi_active_projects = create_card(
        "Active Projects", col1,
        "SELECT COUNT(DISTINCT project_id) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    # fact_financial_dashboard_2026 has no author_name; use rpt_missing_effort
    kpi_active_employees = create_card(
        "Active Employees", col1,
        "SELECT COUNT(DISTINCT author_name) AS value FROM mart.rpt_missing_effort WHERE total_actual_effort_day > 0",
        tags={}, display="scalar"
    )

    # Effort trend - fact_financial_dashboard_2026 has period as text
    effort_trend_sql = """
SELECT period, ROUND(SUM(final_effort)::numeric,1) AS total_effort
FROM mart.fact_financial_dashboard_2026
GROUP BY period ORDER BY period
"""
    ok, msg = test_sql(effort_trend_sql)
    print(f"    [TEST] Effort Trend: {ok} - {msg}")
    card_effort_trend = create_card(
        "Effort Trend by Period", col1, effort_trend_sql, tags={},
        display="area",
        viz={"graph.dimensions": ["period"], "graph.metrics": ["total_effort"]}
    )

    capex_opex_sql = """
SELECT
  CASE WHEN capex_effort > 0 THEN 'Capex' ELSE 'Opex' END AS type,
  ROUND(SUM(capex_effort + opex_effort)::numeric,1) AS effort
FROM mart.fact_financial_dashboard_2026
GROUP BY 1
"""
    # Simpler capex vs opex using direct columns
    capex_opex_sql = """
SELECT 'Capex' AS type, ROUND(SUM(capex_effort)::numeric,1) AS effort
FROM mart.fact_financial_dashboard_2026
UNION ALL
SELECT 'Opex', ROUND(SUM(opex_effort)::numeric,1)
FROM mart.fact_financial_dashboard_2026
"""
    ok, msg = test_sql(capex_opex_sql)
    print(f"    [TEST] Capex vs Opex: {ok} - {msg}")
    card_capex_opex = create_card(
        "Capex vs Opex", col1, capex_opex_sql, tags={},
        display="pie",
        viz={"pie.dimension": "type", "pie.metric": "effort"}
    )

    # --- Tab 2: Portfolio Performance ---
    top_projects_sql = """
SELECT project_name, ROUND(SUM(final_effort)::numeric,1) AS effort
FROM mart.fact_financial_dashboard_2026
GROUP BY project_name ORDER BY effort DESC LIMIT 20
"""
    ok, msg = test_sql(top_projects_sql)
    print(f"    [TEST] Top Projects: {ok} - {msg}")
    card_top_projects = create_card(
        "Top Projects by Effort", col1, top_projects_sql, tags={},
        display="bar",
        viz={"graph.dimensions": ["project_name"], "graph.metrics": ["effort"]}
    )

    by_domain_sql = """
SELECT it_domain, ROUND(SUM(final_effort)::numeric,1) AS effort
FROM mart.fact_financial_dashboard_2026
WHERE it_domain IS NOT NULL
GROUP BY it_domain ORDER BY effort DESC
"""
    card_by_domain = create_card(
        "Effort by IT Domain", col1, by_domain_sql, tags={},
        display="bar",
        viz={"graph.dimensions": ["it_domain"], "graph.metrics": ["effort"]}
    )

    by_category_sql = """
SELECT category, ROUND(SUM(final_effort)::numeric,1) AS effort
FROM mart.fact_financial_dashboard_2026
WHERE category IS NOT NULL
GROUP BY category ORDER BY effort DESC
"""
    card_by_category = create_card(
        "Effort by Category", col1, by_category_sql, tags={},
        display="bar",
        viz={"graph.dimensions": ["category"], "graph.metrics": ["effort"]}
    )

    # --- Tab 3: Financial Summary ---
    kpi_capex = create_card(
        "Capex Effort", col1,
        "SELECT ROUND(SUM(final_effort_capex)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    kpi_opex = create_card(
        "Opex Effort", col1,
        "SELECT ROUND(SUM(final_effort_opex)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )

    fin_summary_sql = """
SELECT project_name, customer, category,
  ROUND(SUM(final_effort)::numeric,1) AS final_effort,
  ROUND(SUM(final_effort_capex)::numeric,1) AS capex_effort,
  ROUND(SUM(final_effort_opex)::numeric,1) AS opex_effort,
  ROUND(SUM(inhouse_effort)::numeric,1) AS inhouse_effort,
  ROUND(SUM(outsource_effort)::numeric,1) AS outsource_effort
FROM mart.fact_financial_dashboard_2026
GROUP BY project_name, customer, category
ORDER BY final_effort DESC
"""
    ok, msg = test_sql(fin_summary_sql)
    print(f"    [TEST] Financial Summary: {ok} - {msg}")
    card_fin_summary = create_card(
        "Project Financial Summary", col1, fin_summary_sql, tags={}, display="table"
    )

    # Build dashcards for dashboard 1 — no date filter (fact_financial_dashboard_2026 uses period text)
    tabs1 = [
        {"id": -1, "name": "Overview"},
        {"id": -2, "name": "Portfolio Performance"},
        {"id": -3, "name": "Financial Summary"}
    ]
    dc1 = []
    # Tab 1 KPIs (no filter mappings since these have no template tags)
    for card_id, col, row in [
        (kpi_total_effort, 0, 0), (kpi_distributed, 6, 0),
        (kpi_active_projects, 12, 0), (kpi_active_employees, 18, 0)
    ]:
        if card_id:
            dc1.append(dashcard(card_id, -1, col, row, w=6, h=3, mappings=[]))
    if card_effort_trend:
        dc1.append(dashcard(card_effort_trend, -1, 0, 3, w=12, h=8, mappings=[]))
    if card_capex_opex:
        dc1.append(dashcard(card_capex_opex, -1, 12, 3, w=12, h=8, mappings=[]))

    # Tab 2
    if card_top_projects:
        dc1.append(dashcard(card_top_projects, -2, 0, 0, w=24, h=8, mappings=[]))
    if card_by_domain:
        dc1.append(dashcard(card_by_domain, -2, 0, 8, w=12, h=8, mappings=[]))
    if card_by_category:
        dc1.append(dashcard(card_by_category, -2, 12, 8, w=12, h=8, mappings=[]))

    # Tab 3
    for card_id, col, row in [(kpi_capex, 0, 0), (kpi_opex, 6, 0)]:
        if card_id:
            dc1.append(dashcard(card_id, -3, col, row, w=6, h=3, mappings=[]))
    if card_fin_summary:
        dc1.append(dashcard(card_fin_summary, -3, 0, 3, w=24, h=12, mappings=[]))

    if dash1_id:
        put_dashboard(dash1_id, tabs1, dc1, [])  # no filters for this dashboard

    # -----------------------------------------------------------------------
    # DASHBOARD 2 — PPM - HR - Timesheet
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 2: Timesheet ===")
    dash2_id = create_dashboard("PPM - HR - Timesheet", ppm_id,
                                "Timesheet compliance: actual vs expected effort per employee and period")
    definitions["dashboards"]["timesheet"] = dash2_id
    col2 = sub["Timesheet"]
    dt2 = date_tag(trx_date_fid)
    txt2 = text_tags("team", "user_name")

    ts_date_tags = merge_tags(dt2, txt2)
    ts_team_tags = merge_tags(dt2, text_tags("team"))
    ts_no_user = merge_tags(dt2, text_tags("team"))

    kpi_actual = create_card(
        "Actual Effort (Person Days)", col2,
        """SELECT ROUND(SUM(total_actual_effort_day)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE 1=1 [[AND {{date_range}}]]
  [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]""",
        tags=ts_date_tags, display="scalar"
    )
    kpi_expected = create_card(
        "Expected Effort (Person Days)", col2,
        """SELECT ROUND(SUM(expected_effort_person_days)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE is_weekend = false [[AND {{date_range}}]]
  [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]""",
        tags=ts_date_tags, display="scalar"
    )
    kpi_ts_pct = create_card(
        "Timesheet Entry %", col2,
        """SELECT ROUND(AVG(timesheet_entry_percentage)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE 1=1 [[AND {{date_range}}]]
  [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]""",
        tags=ts_date_tags, display="scalar"
    )
    kpi_ts_active = create_card(
        "Active Employees", col2,
        """SELECT COUNT(DISTINCT author_name) AS value
FROM mart.rpt_missing_effort
WHERE total_actual_effort_day > 0 [[AND {{date_range}}]]
  [[AND author_team = {{team}}]]""",
        tags=ts_no_user, display="scalar"
    )
    kpi_missing = create_card(
        "Missing Effort Days", col2,
        """SELECT ROUND(SUM(missing_effort_person_days)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE 1=1 [[AND {{date_range}}]]
  [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]""",
        tags=ts_date_tags, display="scalar"
    )
    kpi_day_off = create_card(
        "Day Off Days", col2,
        """SELECT ROUND(SUM(expected_effort_person_days - total_actual_effort_day - missing_effort_person_days)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE is_weekend = false [[AND {{date_range}}]]
  [[AND author_team = {{team}}]]""",
        tags=ts_no_user, display="scalar"
    )

    ts_trend_sql = """
SELECT trx_date,
  ROUND(SUM(total_actual_effort_day)::numeric,2) AS actual_effort,
  ROUND(SUM(expected_effort_person_days)::numeric,2) AS expected_effort
FROM mart.rpt_missing_effort
WHERE is_weekend = false [[AND {{date_range}}]]
  [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]
GROUP BY trx_date ORDER BY trx_date
"""
    ok, msg = test_sql("SELECT trx_date, SUM(total_actual_effort_day) FROM mart.rpt_missing_effort WHERE is_weekend=false GROUP BY trx_date ORDER BY trx_date LIMIT 5")
    print(f"    [TEST] TS Trend: {ok} - {msg}")
    card_ts_trend = create_card(
        "Effort Trend", col2, ts_trend_sql, tags=ts_date_tags,
        display="area",
        viz={"graph.dimensions": ["trx_date"], "graph.metrics": ["actual_effort", "expected_effort"]}
    )

    card_by_team = create_card(
        "Effort by Team", col2,
        """SELECT author_team, ROUND(SUM(total_actual_effort_day)::numeric,1) AS effort
FROM mart.rpt_missing_effort
WHERE author_team IS NOT NULL [[AND {{date_range}}]]
  [[AND author_team = {{team}}]]
GROUP BY author_team ORDER BY effort DESC""",
        tags=ts_no_user, display="pie",
        viz={"pie.dimension": "author_team", "pie.metric": "effort"}
    )

    card_by_unit = create_card(
        "Effort by Unit (Manager)", col2,
        """SELECT deputy_gm_upper_unit, ROUND(SUM(total_actual_effort_day)::numeric,1) AS effort
FROM mart.rpt_missing_effort
WHERE deputy_gm_upper_unit IS NOT NULL [[AND {{date_range}}]]
  [[AND author_team = {{team}}]]
GROUP BY deputy_gm_upper_unit ORDER BY effort DESC""",
        tags=ts_no_user, display="bar",
        viz={"graph.dimensions": ["deputy_gm_upper_unit"], "graph.metrics": ["effort"]}
    )

    # Tab 2 — By Team
    card_by_team_period = create_card(
        "Effort by Team per Period", col2,
        """SELECT period, author_team, ROUND(SUM(total_actual_effort_day)::numeric,1) AS effort
FROM mart.rpt_missing_effort
WHERE author_team IS NOT NULL [[AND {{date_range}}]]
  [[AND author_team = {{team}}]]
GROUP BY period, author_team ORDER BY period""",
        tags=ts_no_user, display="bar",
        viz={"graph.dimensions": ["period", "author_team"], "graph.metrics": ["effort"]}
    )

    # Tab 3 — By Employee
    card_emp_summary = create_card(
        "Employee Timesheet Summary", col2,
        """SELECT author_name, author_team, author_unit,
  ROUND(SUM(total_actual_effort_day)::numeric,1) AS actual_effort,
  ROUND(SUM(expected_effort_person_days)::numeric,1) AS expected_effort,
  ROUND(SUM(missing_effort_person_days)::numeric,1) AS missing_effort,
  ROUND(AVG(timesheet_entry_percentage)::numeric,1) AS avg_entry_pct
FROM mart.rpt_missing_effort
WHERE author_name IS NOT NULL [[AND {{date_range}}]]
  [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]
GROUP BY author_name, author_team, author_unit
ORDER BY missing_effort DESC""",
        tags=ts_date_tags, display="table"
    )

    tabs2 = [
        {"id": -1, "name": "Summary"},
        {"id": -2, "name": "By Team"},
        {"id": -3, "name": "By Employee"}
    ]
    dc2 = []
    date_team_user = [("date_param", "date_range"), ("team_param", "team"), ("user_param", "user_name")]
    date_team = [("date_param", "date_range"), ("team_param", "team")]

    for card_id, col, row, param_list in [
        (kpi_actual, 0, 0, date_team_user),
        (kpi_expected, 4, 0, date_team_user),
        (kpi_ts_pct, 8, 0, date_team_user),
        (kpi_ts_active, 12, 0, date_team),
        (kpi_missing, 16, 0, date_team_user),
        (kpi_day_off, 20, 0, date_team),
    ]:
        if card_id:
            dc2.append(dashcard(card_id, -1, col, row, w=4, h=3,
                                mappings=build_mappings(card_id, has_date=True, text_params=param_list[1:])))
    if card_ts_trend:
        dc2.append(dashcard(card_ts_trend, -1, 0, 3, w=24, h=8,
                            mappings=build_mappings(card_ts_trend, has_date=True, text_params=[("team_param","team"),("user_param","user_name")])))
    if card_by_team:
        dc2.append(dashcard(card_by_team, -1, 0, 11, w=12, h=8,
                            mappings=build_mappings(card_by_team, has_date=True, text_params=[("team_param","team")])))
    if card_by_unit:
        dc2.append(dashcard(card_by_unit, -1, 12, 11, w=12, h=8,
                            mappings=build_mappings(card_by_unit, has_date=True, text_params=[("team_param","team")])))

    if card_by_team_period:
        dc2.append(dashcard(card_by_team_period, -2, 0, 0, w=24, h=10,
                            mappings=build_mappings(card_by_team_period, has_date=True, text_params=[("team_param","team")])))
    if card_emp_summary:
        dc2.append(dashcard(card_emp_summary, -3, 0, 0, w=24, h=14,
                            mappings=build_mappings(card_emp_summary, has_date=True, text_params=[("team_param","team"),("user_param","user_name")])))

    if dash2_id:
        put_dashboard(dash2_id, tabs2, dc2, [DATE_PARAM, TEAM_PARAM, USER_PARAM])

    # -----------------------------------------------------------------------
    # DASHBOARD 3 — PPM - HR - Missing Effort
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 3: Missing Effort ===")
    dash3_id = create_dashboard("PPM - HR - Missing Effort", ppm_id,
                                "Missing timesheet effort analysis by employee, manager, and period")
    definitions["dashboards"]["missing_effort"] = dash3_id
    col3 = sub["Missing Effort"]
    dt3 = date_tag(trx_date_fid)
    me_date_team_user = merge_tags(dt3, text_tags("team", "user_name"))
    me_date_team      = merge_tags(dt3, text_tags("team"))

    kpi_me_ts_pct = create_card(
        "Timesheet Entry %", col3,
        """SELECT ROUND(AVG(timesheet_entry_percentage)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE 1=1 [[AND {{date_range}}]] [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]""",
        tags=me_date_team_user, display="scalar"
    )
    kpi_me_missing = create_card(
        "Total Missing Effort", col3,
        """SELECT ROUND(SUM(missing_effort_person_days)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE 1=1 [[AND {{date_range}}]] [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]""",
        tags=me_date_team_user, display="scalar"
    )
    kpi_me_expected = create_card(
        "Total Expected Effort", col3,
        """SELECT ROUND(SUM(expected_effort_person_days)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE 1=1 [[AND {{date_range}}]] [[AND author_team = {{team}}]]""",
        tags=me_date_team, display="scalar"
    )
    kpi_me_actual = create_card(
        "Total Actual Effort", col3,
        """SELECT ROUND(SUM(total_actual_effort_day)::numeric,1) AS value
FROM mart.rpt_missing_effort
WHERE 1=1 [[AND {{date_range}}]] [[AND author_team = {{team}}]]""",
        tags=me_date_team, display="scalar"
    )
    kpi_me_active = create_card(
        "Active Employees", col3,
        """SELECT COUNT(DISTINCT author_name) AS value
FROM mart.rpt_missing_effort
WHERE total_actual_effort_day > 0 [[AND {{date_range}}]] [[AND author_team = {{team}}]]""",
        tags=me_date_team, display="scalar"
    )
    kpi_me_missing_emp = create_card(
        "Employees with Missing", col3,
        """SELECT COUNT(DISTINCT author_name) AS value
FROM mart.rpt_missing_effort
WHERE missing_effort_person_days > 0 [[AND {{date_range}}]] [[AND author_team = {{team}}]]""",
        tags=me_date_team, display="scalar"
    )

    card_me_donut = create_card(
        "Missing by Team", col3,
        """SELECT author_team, ROUND(SUM(missing_effort_person_days)::numeric,1) AS missing
FROM mart.rpt_missing_effort
WHERE missing_effort_person_days > 0 AND author_team IS NOT NULL
  [[AND {{date_range}}]] [[AND author_team = {{team}}]]
GROUP BY author_team ORDER BY missing DESC""",
        tags=me_date_team, display="pie",
        viz={"pie.dimension": "author_team", "pie.metric": "missing"}
    )

    card_me_by_emp = create_card(
        "Missing by Employee", col3,
        """SELECT author_name, author_team,
  ROUND(SUM(missing_effort_person_days)::numeric,2) AS missing_effort,
  ROUND(SUM(total_actual_effort_day)::numeric,2) AS actual_effort,
  ROUND(SUM(expected_effort_person_days)::numeric,2) AS expected_effort,
  ROUND(AVG(timesheet_entry_percentage)::numeric,1) AS timesheet_pct
FROM mart.rpt_missing_effort
WHERE 1=1 [[AND {{date_range}}]] [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]
GROUP BY author_name, author_team ORDER BY missing_effort DESC""",
        tags=me_date_team_user, display="table"
    )

    card_me_by_mgr = create_card(
        "Missing by Manager Unit", col3,
        """SELECT deputy_gm_upper_unit,
  ROUND(SUM(missing_effort_person_days)::numeric,2) AS missing_effort,
  COUNT(DISTINCT author_name) AS employees,
  ROUND(AVG(timesheet_entry_percentage)::numeric,1) AS timesheet_pct
FROM mart.rpt_missing_effort
WHERE deputy_gm_upper_unit IS NOT NULL [[AND {{date_range}}]] [[AND author_team = {{team}}]]
GROUP BY deputy_gm_upper_unit ORDER BY missing_effort DESC""",
        tags=me_date_team, display="table"
    )

    card_me_daily = create_card(
        "Daily Missing Effort", col3,
        """SELECT author_name, period,
  SUM(CASE WHEN EXTRACT(DAY FROM trx_date)::int BETWEEN 1  AND 7  THEN missing_effort_person_days END) AS week1,
  SUM(CASE WHEN EXTRACT(DAY FROM trx_date)::int BETWEEN 8  AND 14 THEN missing_effort_person_days END) AS week2,
  SUM(CASE WHEN EXTRACT(DAY FROM trx_date)::int BETWEEN 15 AND 21 THEN missing_effort_person_days END) AS week3,
  SUM(CASE WHEN EXTRACT(DAY FROM trx_date)::int BETWEEN 22 AND 31 THEN missing_effort_person_days END) AS week4,
  ROUND(SUM(missing_effort_person_days)::numeric,2) AS total_missing
FROM mart.rpt_missing_effort
WHERE missing_effort_person_days > 0 AND author_name IS NOT NULL
  [[AND {{date_range}}]] [[AND author_team = {{team}}]] [[AND author_name = {{user_name}}]]
GROUP BY author_name, period ORDER BY period DESC, total_missing DESC""",
        tags=me_date_team_user, display="table"
    )

    tabs3 = [
        {"id": -1, "name": "Summary"},
        {"id": -2, "name": "By Employee"},
        {"id": -3, "name": "By Manager"},
        {"id": -4, "name": "Daily Detail"}
    ]
    dc3 = []
    for card_id, col, row, has_user in [
        (kpi_me_ts_pct, 0, 0, True),
        (kpi_me_missing, 4, 0, True),
        (kpi_me_expected, 8, 0, False),
        (kpi_me_actual, 12, 0, False),
        (kpi_me_active, 16, 0, False),
        (kpi_me_missing_emp, 20, 0, False),
    ]:
        if card_id:
            tparams = [("team_param","team")]
            if has_user:
                tparams.append(("user_param","user_name"))
            dc3.append(dashcard(card_id, -1, col, row, w=4, h=3,
                                mappings=build_mappings(card_id, has_date=True, text_params=tparams)))
    if card_me_donut:
        dc3.append(dashcard(card_me_donut, -1, 0, 3, w=12, h=8,
                            mappings=build_mappings(card_me_donut, has_date=True, text_params=[("team_param","team")])))

    if card_me_by_emp:
        dc3.append(dashcard(card_me_by_emp, -2, 0, 0, w=24, h=12,
                            mappings=build_mappings(card_me_by_emp, has_date=True,
                                                    text_params=[("team_param","team"),("user_param","user_name")])))
    if card_me_by_mgr:
        dc3.append(dashcard(card_me_by_mgr, -3, 0, 0, w=24, h=12,
                            mappings=build_mappings(card_me_by_mgr, has_date=True, text_params=[("team_param","team")])))
    if card_me_daily:
        dc3.append(dashcard(card_me_daily, -4, 0, 0, w=24, h=14,
                            mappings=build_mappings(card_me_daily, has_date=True,
                                                    text_params=[("team_param","team"),("user_param","user_name")])))

    if dash3_id:
        put_dashboard(dash3_id, tabs3, dc3, [DATE_PARAM, TEAM_PARAM, USER_PARAM])

    # -----------------------------------------------------------------------
    # DASHBOARD 4 — PPM - Finance - Distributed Effort
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 4: Distributed Effort ===")
    dash4_id = create_dashboard("PPM - Finance - Distributed Effort", ppm_id,
                                "Distributed effort analysis by customer, product, and tribe")
    definitions["dashboards"]["distributed"] = dash4_id
    col4 = sub["Distributed"]

    # Note: 2025 distributed tables are empty; 2026 has different schema.
    # Use fact_distributed_efforts_2026 only (has distributed_effort, final_effort).
    # For capex/opex we cast from fact_financial_dashboard_2026 which shares the period key.
    dist_union_simple = """(
  SELECT period, project_name, customer, it_domain, tribe, product,
         business_line, financial_code, is_outsource_inhouse,
         final_effort, distributed_effort,
         NULL::numeric AS final_effort_capex, NULL::numeric AS final_effort_opex
  FROM mart.fact_distributed_efforts_2026
) d"""

    # Test the union
    ok, msg = test_sql(f"SELECT COUNT(*) FROM {dist_union_simple}")
    print(f"    [TEST] Distributed UNION: {ok} - {msg}")

    kpi_dist_final = create_card(
        "Total Final Effort", col4,
        f"SELECT ROUND(SUM(final_effort)::numeric,1) AS value FROM {dist_union_simple}",
        tags={}, display="scalar"
    )
    kpi_dist_distributed = create_card(
        "Total Distributed Effort", col4,
        f"SELECT ROUND(SUM(distributed_effort)::numeric,1) AS value FROM {dist_union_simple}",
        tags={}, display="scalar"
    )
    kpi_dist_capex = create_card(
        "Capex Effort (Financial)", col4,
        "SELECT ROUND(SUM(final_effort_capex)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    kpi_dist_opex = create_card(
        "Opex Effort (Financial)", col4,
        "SELECT ROUND(SUM(final_effort_opex)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )

    dist_trend_sql = f"""
SELECT period,
  ROUND(SUM(final_effort)::numeric,1) AS final_effort,
  ROUND(SUM(distributed_effort)::numeric,1) AS distributed_effort
FROM {dist_union_simple}
GROUP BY period ORDER BY period
"""
    ok, msg = test_sql(dist_trend_sql)
    print(f"    [TEST] Dist Trend: {ok} - {msg}")
    card_dist_trend = create_card(
        "Distributed Effort Trend by Period", col4, dist_trend_sql, tags={},
        display="line",
        viz={"graph.dimensions": ["period"], "graph.metrics": ["final_effort", "distributed_effort"]}
    )

    dist_capex_sql = """
SELECT 'Capex' AS type, ROUND(SUM(final_effort_capex)::numeric,1) AS effort
FROM mart.fact_financial_dashboard_2026
UNION ALL
SELECT 'Opex', ROUND(SUM(final_effort_opex)::numeric,1)
FROM mart.fact_financial_dashboard_2026
"""
    ok, msg = test_sql(dist_capex_sql)
    print(f"    [TEST] Dist Capex/Opex: {ok} - {msg}")
    card_dist_capex = create_card(
        "Capex vs Opex", col4, dist_capex_sql, tags={},
        display="pie",
        viz={"pie.dimension": "type", "pie.metric": "effort"}
    )

    # Tab 2 — By Customer
    by_customer_sql = f"""
SELECT customer, ROUND(SUM(distributed_effort)::numeric,1) AS distributed_effort
FROM {dist_union_simple}
WHERE customer IS NOT NULL
GROUP BY customer ORDER BY distributed_effort DESC
"""
    ok, msg = test_sql(by_customer_sql)
    print(f"    [TEST] Dist By Customer: {ok} - {msg}")
    card_dist_customer = create_card(
        "Effort by Customer", col4, by_customer_sql, tags={},
        display="bar",
        viz={"graph.dimensions": ["customer"], "graph.metrics": ["distributed_effort"]}
    )

    # Tab 3 — By Product
    by_product_sql = f"""
SELECT product, ROUND(SUM(distributed_effort)::numeric,1) AS distributed_effort
FROM {dist_union_simple}
WHERE product IS NOT NULL
GROUP BY product ORDER BY distributed_effort DESC
"""
    card_dist_product = create_card(
        "Effort by Product", col4, by_product_sql, tags={},
        display="bar",
        viz={"graph.dimensions": ["product"], "graph.metrics": ["distributed_effort"]}
    )

    # Tab 4 — By Tribe
    by_tribe_sql = f"""
SELECT tribe, ROUND(SUM(distributed_effort)::numeric,1) AS distributed_effort
FROM {dist_union_simple}
WHERE tribe IS NOT NULL
GROUP BY tribe ORDER BY distributed_effort DESC
"""
    card_dist_tribe = create_card(
        "Effort by Tribe", col4, by_tribe_sql, tags={},
        display="bar",
        viz={"graph.dimensions": ["tribe"], "graph.metrics": ["distributed_effort"]}
    )

    tabs4 = [
        {"id": -1, "name": "Summary"},
        {"id": -2, "name": "By Customer"},
        {"id": -3, "name": "By Product"},
        {"id": -4, "name": "By Tribe"}
    ]
    dc4 = []
    for card_id, col, row in [
        (kpi_dist_final, 0, 0), (kpi_dist_distributed, 6, 0),
        (kpi_dist_capex, 12, 0), (kpi_dist_opex, 18, 0)
    ]:
        if card_id:
            dc4.append(dashcard(card_id, -1, col, row, w=6, h=3, mappings=[]))
    if card_dist_trend:
        dc4.append(dashcard(card_dist_trend, -1, 0, 3, w=14, h=8, mappings=[]))
    if card_dist_capex:
        dc4.append(dashcard(card_dist_capex, -1, 14, 3, w=10, h=8, mappings=[]))
    if card_dist_customer:
        dc4.append(dashcard(card_dist_customer, -2, 0, 0, w=24, h=10, mappings=[]))
    if card_dist_product:
        dc4.append(dashcard(card_dist_product, -3, 0, 0, w=24, h=10, mappings=[]))
    if card_dist_tribe:
        dc4.append(dashcard(card_dist_tribe, -4, 0, 0, w=24, h=10, mappings=[]))

    if dash4_id:
        put_dashboard(dash4_id, tabs4, dc4, [])

    # -----------------------------------------------------------------------
    # DASHBOARD 5 — PPM - Finance - Distribution Steps
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 5: Distribution Steps ===")
    dash5_id = create_dashboard("PPM - Finance - Distribution Steps", ppm_id,
                                "Step-by-step effort distribution methodology overview")
    definitions["dashboards"]["distribution_steps"] = dash5_id
    col5 = sub["Financial"]

    # fact_financial_dashboard_2026: period (text), no date column
    kpi_ds_total = create_card(
        "Total Final Effort", col5,
        "SELECT ROUND(SUM(final_effort)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    kpi_ds_base = create_card(
        "Base Effort (Logged Time)", col5,
        "SELECT ROUND(SUM(logged_time_person_day)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    kpi_ds_team = create_card(
        "Team Effort", col5,
        "SELECT ROUND(SUM(team_effort)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    kpi_ds_tribe = create_card(
        "Tribe Effort", col5,
        "SELECT ROUND(SUM(tribe_effort)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )
    kpi_ds_distributed = create_card(
        "Total Distributed", col5,
        "SELECT ROUND(SUM(total_distributed_all)::numeric,1) AS value FROM mart.fact_financial_dashboard_2026",
        tags={}, display="scalar"
    )

    ds_detail_sql = """
SELECT period, project_name, customer,
  ROUND(logged_time_person_day::numeric,2) AS base_effort,
  ROUND(team_effort::numeric,2) AS team_effort,
  ROUND(tribe_effort::numeric,2) AS tribe_effort,
  ROUND(final_effort::numeric,2) AS final_effort,
  ROUND(total_distributed_all::numeric,2) AS distributed_effort,
  ROUND(final_effort_capex::numeric,2) AS capex_effort,
  ROUND(final_effort_opex::numeric,2) AS opex_effort
FROM mart.fact_financial_dashboard_2026
ORDER BY period DESC, final_effort DESC
LIMIT 500
"""
    ok, msg = test_sql(ds_detail_sql)
    print(f"    [TEST] Distribution Detail: {ok} - {msg}")
    card_ds_detail = create_card(
        "Distribution Detail", col5, ds_detail_sql, tags={}, display="table"
    )

    ds_by_period_sql = """
SELECT period,
  ROUND(SUM(logged_time_person_day)::numeric,1) AS base_effort,
  ROUND(SUM(team_effort)::numeric,1) AS team_effort,
  ROUND(SUM(tribe_effort)::numeric,1) AS tribe_effort,
  ROUND(SUM(final_effort)::numeric,1) AS final_effort
FROM mart.fact_financial_dashboard_2026
GROUP BY period ORDER BY period
"""
    card_ds_trend = create_card(
        "Effort Steps by Period", col5, ds_by_period_sql, tags={},
        display="bar",
        viz={"graph.dimensions": ["period"], "graph.metrics": ["base_effort", "team_effort", "tribe_effort", "final_effort"]}
    )

    tabs5 = [{"id": -1, "name": "Overview"}, {"id": -2, "name": "Detailed Data"}]
    dc5 = []
    for card_id, col, row in [
        (kpi_ds_total, 0, 0), (kpi_ds_base, 4, 0), (kpi_ds_team, 8, 0),
        (kpi_ds_tribe, 12, 0), (kpi_ds_distributed, 18, 0)
    ]:
        if card_id:
            dc5.append(dashcard(card_id, -1, col, row, w=4, h=3, mappings=[]))
    if card_ds_trend:
        dc5.append(dashcard(card_ds_trend, -1, 0, 3, w=24, h=8, mappings=[]))
    if card_ds_detail:
        dc5.append(dashcard(card_ds_detail, -2, 0, 0, w=24, h=14, mappings=[]))

    if dash5_id:
        put_dashboard(dash5_id, tabs5, dc5, [])

    # -----------------------------------------------------------------------
    # DASHBOARD 6 — PPM - Leadership - Strategic Portfolio
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 6: Strategic Portfolio ===")
    dash6_id = create_dashboard("PPM - Leadership - Strategic Portfolio", ppm_id,
                                "Strategic portfolio overview with project status and completion metrics")
    definitions["dashboards"]["portfolio"] = dash6_id
    col6 = sub["Portfolio"]

    # dim_projects columns: project_id, project_key, project_name, open_closed (status),
    # customer, it_domain, product, tribe, business_line, financial_code,
    # completion_pct, total_hours_logged, total_issues, completed_issues, in_progress_issues, todo_issues

    kpi_total_proj = create_card(
        "Total Projects", col6,
        "SELECT COUNT(DISTINCT project_key) AS value FROM core.dim_projects",
        tags={}, display="scalar"
    )
    kpi_open_proj = create_card(
        "Open Projects", col6,
        "SELECT COUNT(DISTINCT project_key) AS value FROM core.dim_projects WHERE open_closed = 'open'",
        tags={}, display="scalar"
    )
    kpi_avg_completion = create_card(
        "Avg Completion %", col6,
        "SELECT ROUND(AVG(completion_pct)::numeric,1) AS value FROM core.dim_projects WHERE completion_pct IS NOT NULL",
        tags={}, display="scalar"
    )

    card_status_pie = create_card(
        "Projects by Status", col6,
        """SELECT open_closed AS status, COUNT(*) AS count
FROM core.dim_projects GROUP BY open_closed""",
        tags={}, display="pie",
        viz={"pie.dimension": "status", "pie.metric": "count"}
    )

    card_by_domain = create_card(
        "Projects by IT Domain", col6,
        """SELECT COALESCE(it_domain, 'Unknown') AS it_domain,
  COUNT(DISTINCT project_key) AS projects
FROM core.dim_projects GROUP BY it_domain ORDER BY projects DESC""",
        tags={}, display="bar",
        viz={"graph.dimensions": ["it_domain"], "graph.metrics": ["projects"]}
    )

    # Use fact_worklogs for effort (no join on dim_issues needed for basic summary)
    proj_summary_sql = """
SELECT p.project_key, p.project_name, p.customer, p.it_domain, p.tribe,
  p.open_closed AS status,
  p.completion_pct,
  p.total_issues, p.completed_issues, p.in_progress_issues, p.todo_issues,
  ROUND(p.total_hours_logged::numeric,1) AS hours_logged
FROM core.dim_projects p
ORDER BY p.open_closed, p.project_name
"""
    ok, msg = test_sql(proj_summary_sql)
    print(f"    [TEST] Project Summary: {ok} - {msg}")
    card_proj_summary = create_card(
        "Project Summary", col6, proj_summary_sql, tags={}, display="table"
    )

    # Full project detail with issue breakdown
    proj_detail_sql = """
SELECT p.project_key, p.project_name, p.customer, p.it_domain, p.product, p.tribe,
  p.business_line, p.financial_code, p.open_closed AS status,
  p.completion_pct, p.total_issues, p.completed_issues,
  ROUND(p.total_hours_logged::numeric,1) AS hours_logged,
  p._etl_date AS last_etl
FROM core.dim_projects p
ORDER BY p.project_name
"""
    card_proj_detail = create_card(
        "Full Project Detail", col6, proj_detail_sql, tags={}, display="table"
    )

    tabs6 = [{"id": -1, "name": "Portfolio Summary"}, {"id": -2, "name": "Project Detail"}]
    dc6 = []
    for card_id, col, row in [
        (kpi_total_proj, 0, 0), (kpi_open_proj, 6, 0), (kpi_avg_completion, 12, 0)
    ]:
        if card_id:
            dc6.append(dashcard(card_id, -1, col, row, w=6, h=3, mappings=[]))
    if card_status_pie:
        dc6.append(dashcard(card_status_pie, -1, 0, 3, w=8, h=8, mappings=[]))
    if card_by_domain:
        dc6.append(dashcard(card_by_domain, -1, 8, 3, w=16, h=8, mappings=[]))
    if card_proj_summary:
        dc6.append(dashcard(card_proj_summary, -1, 0, 11, w=24, h=12, mappings=[]))
    if card_proj_detail:
        dc6.append(dashcard(card_proj_detail, -2, 0, 0, w=24, h=14, mappings=[]))

    if dash6_id:
        put_dashboard(dash6_id, tabs6, dc6, [])

    # -----------------------------------------------------------------------
    # DASHBOARD 7 — PPM - Ops - Data Quality and Pipeline
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 7: Data Quality and Pipeline ===")
    dash7_id = create_dashboard("PPM - Ops - Data Quality and Pipeline", ppm_id,
                                "Data quality checks, ETL freshness, and missing data reports")
    definitions["dashboards"]["data_quality"] = dash7_id
    col7 = sub["Data Quality"]

    card_dq_proj = create_card(
        "Projects Missing Fields", col7,
        """SELECT project_key, project_name
FROM core.dim_projects
WHERE project_name IS NULL OR project_key IS NULL
LIMIT 100""",
        tags={}, display="table"
    )

    card_dq_users = create_card(
        "Users Missing Team or Manager", col7,
        """SELECT display_name, email
FROM core.dim_users
WHERE team IS NULL OR display_name IS NULL
LIMIT 100""",
        tags={}, display="table"
    )

    card_issues_no_log = create_card(
        "Issues Without Worklogs", col7,
        """SELECT COUNT(DISTINCT i.issue_key) AS value
FROM core.dim_issues i
LEFT JOIN core.fact_worklogs w ON i.issue_key = w.issue_key
WHERE w.issue_key IS NULL AND i.status_category != 'Done' AND i.is_subtask = false""",
        tags={}, display="scalar"
    )

    null_summary_sql = """
SELECT 'Projects without Customer' AS check_name, COUNT(*) AS count
FROM core.dim_projects WHERE customer IS NULL OR customer = ''
UNION ALL
SELECT 'Projects without IT Domain', COUNT(*)
FROM core.dim_projects WHERE it_domain IS NULL OR it_domain = ''
UNION ALL
SELECT 'Projects without Financial Code', COUNT(*)
FROM core.dim_projects WHERE financial_code IS NULL OR financial_code = ''
UNION ALL
SELECT 'Users without Team', COUNT(*)
FROM core.dim_users WHERE team IS NULL OR team = ''
UNION ALL
SELECT 'Users without Manager', COUNT(*)
FROM core.dim_users WHERE manager_director IS NULL OR manager_director = ''
UNION ALL
SELECT 'Worklogs without Capex/Opex', COUNT(*)
FROM core.fact_worklogs WHERE capex_opex IS NULL
ORDER BY count DESC
"""
    ok, msg = test_sql(null_summary_sql)
    print(f"    [TEST] Null Summary: {ok} - {msg}")
    card_null_summary = create_card(
        "Missing Field Summary", col7, null_summary_sql, tags={},
        display="bar",
        viz={"graph.dimensions": ["check_name"], "graph.metrics": ["count"]}
    )

    etl_sql = """
SELECT 'rpt_missing_effort' AS table_name, MAX(trx_date)::text AS latest_date, COUNT(*) AS row_count
FROM mart.rpt_missing_effort
UNION ALL
SELECT 'fact_distributed_efforts_2026', MAX(period), COUNT(*)
FROM mart.fact_distributed_efforts_2026
UNION ALL
SELECT 'fact_financial_dashboard_2026', MAX(period), COUNT(*)
FROM mart.fact_financial_dashboard_2026
UNION ALL
SELECT 'fact_worklogs', MAX(trx_date::text), COUNT(*)
FROM core.fact_worklogs
UNION ALL
SELECT 'dim_projects', MAX(_etl_date::text), COUNT(*)
FROM core.dim_projects
UNION ALL
SELECT 'dim_users', MAX(_etl_date::text), COUNT(*)
FROM core.dim_users
"""
    ok, msg = test_sql(etl_sql)
    print(f"    [TEST] ETL Status: {ok} - {msg}")
    card_etl = create_card(
        "Latest ETL per Table", col7, etl_sql, tags={}, display="table"
    )

    tabs7 = [
        {"id": -1, "name": "Error Checks"},
        {"id": -2, "name": "Missing Data"},
        {"id": -3, "name": "ETL Status"}
    ]
    dc7 = []
    if card_dq_proj:
        dc7.append(dashcard(card_dq_proj, -1, 0, 0, w=24, h=10, mappings=[]))
    if card_dq_users:
        dc7.append(dashcard(card_dq_users, -1, 0, 10, w=24, h=10, mappings=[]))
    if card_issues_no_log:
        dc7.append(dashcard(card_issues_no_log, -2, 0, 0, w=6, h=3, mappings=[]))
    if card_null_summary:
        dc7.append(dashcard(card_null_summary, -2, 0, 3, w=24, h=10, mappings=[]))
    if card_etl:
        dc7.append(dashcard(card_etl, -3, 0, 0, w=24, h=10, mappings=[]))

    if dash7_id:
        put_dashboard(dash7_id, tabs7, dc7, [])

    # -----------------------------------------------------------------------
    # DASHBOARD 8 — PPM - Ops - Master Data
    # -----------------------------------------------------------------------
    print("\n=== Dashboard 8: Master Data ===")
    dash8_id = create_dashboard("PPM - Ops - Master Data", ppm_id,
                                "Reference data: projects, employees, issue types")
    definitions["dashboards"]["master_data"] = dash8_id
    col8 = sub["Master Data"]

    card_all_projects = create_card(
        "All Projects", col8,
        """SELECT project_key, project_name, project_type, customer, it_domain,
  product, tribe, business_line, financial_code, open_closed AS status,
  completion_pct, total_issues, ROUND(total_hours_logged::numeric,1) AS total_hours,
  _etl_date
FROM core.dim_projects ORDER BY project_name""",
        tags={}, display="table"
    )

    card_all_users = create_card(
        "All Employees", col8,
        """SELECT display_name, email, team, unit, manager_director, manager_deputy_gm,
  deputy_gm_upper_unit, outsource_inhouse, is_active, hr_status,
  ROUND(total_hours_logged::numeric,1) AS total_hours
FROM core.dim_users ORDER BY display_name""",
        tags={}, display="table"
    )

    card_issue_types = create_card(
        "Issue Type Inventory", col8,
        """SELECT issue_type, issue_type_name, capex_opex, issue_type_category,
  COUNT(*) AS worklog_count,
  ROUND(SUM(time_spent_hours)::numeric,1) AS total_hours
FROM core.fact_worklogs
WHERE issue_type_name IS NOT NULL
GROUP BY issue_type, issue_type_name, capex_opex, issue_type_category
ORDER BY worklog_count DESC""",
        tags={}, display="table"
    )

    tabs8 = [
        {"id": -1, "name": "Projects"},
        {"id": -2, "name": "Employees"},
        {"id": -3, "name": "Issue Types"}
    ]
    dc8 = []
    if card_all_projects:
        dc8.append(dashcard(card_all_projects, -1, 0, 0, w=24, h=14, mappings=[]))
    if card_all_users:
        dc8.append(dashcard(card_all_users, -2, 0, 0, w=24, h=14, mappings=[]))
    if card_issue_types:
        dc8.append(dashcard(card_issue_types, -3, 0, 0, w=24, h=12, mappings=[]))

    if dash8_id:
        put_dashboard(dash8_id, tabs8, dc8, [])

    # -----------------------------------------------------------------------
    # Update PPM Home with real dashboard IDs
    # -----------------------------------------------------------------------
    if dash0_id:
        print("\n=== Updating PPM Home with dashboard links ===")
        dash_links = [
            (dash1_id, "Executive Overview", "Portfolyo ozeti, KPI'lar ve finansal ozet"),
            (dash2_id, "Timesheet", "Gercek vs beklenen mesai takibi"),
            (dash3_id, "Missing Effort", "Eksik timesheet analizi"),
            (dash4_id, "Distributed Effort", "Musteri/urun bazinda dagitilmis mesai"),
            (dash5_id, "Distribution Steps", "Dagitim adimlari metodolojisi"),
            (dash6_id, "Strategic Portfolio", "Proje durumu ve tamamlanma metrikleri"),
            (dash7_id, "Data Quality and Pipeline", "Veri kalitesi ve ETL durumu"),
            (dash8_id, "Master Data", "Referans veriler: projeler, calisanlar"),
        ]
        home_cards = [
            text_dashcard(
                "# PPM Insights\n\nProje ve Portfolyo Yonetimi veri platformuna hos geldiniz.\n\n"
                "Asagidaki kartlardan ilgili dashboard'a gidin.",
                -1, 0, 0, w=24, h=3
            )
        ]
        col_positions_home = [0, 8, 16, 0, 8, 16, 0, 8]
        row_positions_home = [3, 3, 3, 7, 7, 7, 11, 11]
        for i, (did, title, desc) in enumerate(dash_links):
            link_text = f"### {title}\n\n{desc}"
            if did:
                link_text += f"\n\n[Ac](/dashboard/{did})"
            home_cards.append(
                text_dashcard(link_text, -1, col_positions_home[i], row_positions_home[i], w=8, h=4)
            )
        put_dashboard(dash0_id, [{"id": -1, "name": "Home"}], home_cards, [])

    # -----------------------------------------------------------------------
    # Save definitions
    # -----------------------------------------------------------------------
    print("\n=== Saving Definitions ===")
    with open(DEFINITIONS_FILE, "w") as f:
        json.dump(definitions, f, indent=2)
    print(f"  Saved to {DEFINITIONS_FILE}")

    print("\n=== Dashboard URLs ===")
    for name, did in definitions["dashboards"].items():
        if did:
            print(f"  {name}: {BASE_URL}/dashboard/{did}")

    print("\n=== Models ===")
    for name, cid in definitions["models"].items():
        if cid:
            print(f"  {name}: {BASE_URL}/question/{cid}")

    print(f"\n[DONE] Collection: {BASE_URL}/collection/{ppm_id}")
    return definitions


# ---------------------------------------------------------------------------
# dbt Exposures
# ---------------------------------------------------------------------------
def write_dbt_exposures(definitions):
    exposures_path = os.path.join(os.path.dirname(__file__), "..", "dbt", "models", "exposures.yml")
    base_url = BASE_URL
    dash = definitions["dashboards"]
    models = definitions["models"]

    exposure_defs = [
        ("ppm_home", "PPM Home", "dashboard", "high",
         f"{base_url}/dashboard/{dash.get('home', '')}",
         "PPM Insights homepage with links to all dashboards",
         []),
        ("ppm_executive_overview", "PPM - Executive - Overview", "dashboard", "high",
         f"{base_url}/dashboard/{dash.get('overview', '')}",
         "Executive overview: KPIs, effort trends, capex/opex, top projects",
         ["fact_financial_dashboard_2026"]),
        ("ppm_timesheet", "PPM - HR - Timesheet", "dashboard", "high",
         f"{base_url}/dashboard/{dash.get('timesheet', '')}",
         "Timesheet compliance: actual vs expected effort by employee and team",
         ["rpt_missing_effort"]),
        ("ppm_missing_effort", "PPM - HR - Missing Effort", "dashboard", "high",
         f"{base_url}/dashboard/{dash.get('missing_effort', '')}",
         "Missing effort analysis with employee and manager drill-downs",
         ["rpt_missing_effort"]),
        ("ppm_distributed_effort", "PPM - Finance - Distributed Effort", "dashboard", "high",
         f"{base_url}/dashboard/{dash.get('distributed', '')}",
         "Distributed effort by customer, product, and tribe",
         ["fact_distributed_efforts_2025_01_06", "fact_distributed_efforts_2025_07_12", "fact_distributed_efforts_2026"]),
        ("ppm_distribution_steps", "PPM - Finance - Distribution Steps", "dashboard", "medium",
         f"{base_url}/dashboard/{dash.get('distribution_steps', '')}",
         "Step-by-step effort distribution methodology",
         ["fact_financial_dashboard_2026"]),
        ("ppm_strategic_portfolio", "PPM - Leadership - Strategic Portfolio", "dashboard", "high",
         f"{base_url}/dashboard/{dash.get('portfolio', '')}",
         "Strategic portfolio overview with project status and completion metrics",
         ["dim_projects"]),
        ("ppm_data_quality", "PPM - Ops - Data Quality and Pipeline", "dashboard", "medium",
         f"{base_url}/dashboard/{dash.get('data_quality', '')}",
         "Data quality checks: missing metadata, ETL freshness",
         ["dim_projects", "dim_users", "fact_worklogs"]),
        ("ppm_master_data", "PPM - Ops - Master Data", "dashboard", "high",
         f"{base_url}/dashboard/{dash.get('master_data', '')}",
         "Reference data: all projects, employees, issue types",
         ["dim_projects", "dim_users", "fact_worklogs"]),
    ]

    lines = ["version: 2", "", "exposures:", ""]
    for name, label, typ, maturity, url, desc, deps in exposure_defs:
        lines += [
            f"  - name: {name}",
            f'    label: "{label}"',
            f"    type: {typ}",
            f"    maturity: {maturity}",
            f'    url: "{url}"',
            f"    description: >",
            f"      {desc}",
            f"    depends_on:",
        ]
        for dep in deps:
            lines.append(f"      - ref('{dep}')")
        lines += [
            f"    owner:",
            f"      name: PPM Team",
            f"      email: admin@jppm.local",
            "",
        ]

    with open(exposures_path, "w") as f:
        f.write("\n".join(lines))
    print(f"[dbt] Exposures written to {exposures_path}")


if __name__ == "__main__":
    defs = main()
    write_dbt_exposures(defs)
