# Metabase Skill — PPM Data Stack

## Connection & Auth

- **URL**: http://localhost:3000
- **Admin email**: `admin@jppm.local`
- **Admin password**: `Jppm@min123`
- **DB_ID**: `2` (PPM Data Warehouse — postgres)

```python
# Session token (use for all API calls)
import urllib.request, json

def get_session():
    r = urllib.request.urlopen(urllib.request.Request(
        "http://localhost:3000/api/session",
        data=json.dumps({"username": "admin@jppm.local", "password": "Jppm@min123"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST"
    ))
    return json.loads(r.read())["id"]
```

## MCP — Claude Code Integration

Metabase has a built-in MCP server (v0.62.3+, available in OSS).

- **MCP endpoint**: `http://localhost:3000/api/metabase-mcp`
- **API key**: `mb_CgSDaave8BeS3QS2m4X+g4vqVrdQrkoIahyxMPLGWDA=` (regenerate: `PUT /api/api-key/1/regenerate`)
- **Config**: `.claude/settings.json` in the project root (already configured)
- **Tools**: `execute_sql`, `create_question`, `create_dashboard`, `update_dashboard`, `search`, `construct_query`

To regenerate API key:
```bash
SESSION=$(curl -s -X POST http://localhost:3000/api/session -H "Content-Type: application/json" \
  -d '{"username":"admin@jppm.local","password":"Jppm@min123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X PUT http://localhost:3000/api/api-key/1/regenerate -H "X-Metabase-Session: $SESSION"
```

## Data Model — Critical Notes

`fact_worklogs` has **133K+ rows** but `project_key` column is **NULL for all rows** (dbt join issue — `fact_worklogs.issue_key` and `dim_issues.issue_key` don't overlap).

**Workaround**: extract project from issue_key pattern `DG-176` → `DG`:
```sql
SPLIT_PART(issue_key, '-', 1) AS project_key
```

**Use this pattern everywhere** when joining fact_worklogs to project-level data:
```sql
-- Wrong (returns 0 rows):
LEFT JOIN core.fact_worklogs w ON i.issue_key = w.issue_key

-- Correct for project hours:
LEFT JOIN (
    SELECT SPLIT_PART(issue_key, '-', 1) AS project_key,
           SUM(time_spent_hours) AS total_hours
    FROM core.fact_worklogs WHERE issue_key IS NOT NULL
    GROUP BY 1
) wl ON p.project_key = wl.project_key
```

Also: `fact_worklogs.trx_date` has future dates up to 2031 (Jira data quality). Add `AND w.trx_date <= CURRENT_DATE` when needed.

**Key tables**:
| Table | Rows | Project Key | Notes |
|-------|------|-------------|-------|
| `core.dim_projects` | ~491 | `project_key` ✓ | |
| `core.dim_issues` | 55K | `project_key` ✓ | Issues but NOT the same as fact_worklogs issue_keys |
| `core.fact_worklogs` | 133K | NULL ✗ | Use `SPLIT_PART(issue_key,'-',1)` |
| `core.dim_users` | ~500 | — | Join: `w.author_id = u.user_id` ✓ |

## Dashboard Patterns

### Create/upsert a question with optional project filter

```python
def upsert_question(session, name, sql, display="table", existing_id=None, template_tags=None):
    payload = {
        "name": name, "display": display,
        "dataset_query": {
            "database": 2, "type": "native",
            "native": {"query": sql, "template-tags": template_tags or {}}
        },
        "collection_id": None,
        "visualization_settings": {},
    }
    method = "PUT" if existing_id else "POST"
    path = f"/card/{existing_id}" if existing_id else "/card"
    # ... call API
```

### Optional project filter template tag

```python
PROJECT_TAG = {
    "project_key": {
        "id": "11111111-1111-1111-1111-111111111111",  # static UUID for idempotency
        "name": "project_key",
        "display-name": "Project",
        "type": "text",
        "required": False,
    }
}
```

SQL pattern (optional filter — omits WHERE when not set):
```sql
WHERE is_subtask = false
  [[AND project_key = {{project_key}}]]      -- for dim_issues queries
  [[AND SPLIT_PART(issue_key, '-', 1) = {{project_key}}]]  -- for fact_worklogs
```

### Add filter to dashboard + parameter mapping

```python
PROJECT_PARAM = {
    "id": "project_key_param",
    "name": "Project",
    "type": "string/=",
    "slug": "project_key",
    "sectionId": "string",
    "default": None,
}

# In PUT /api/dashboard/{id}:
{
    "width": "full",
    "parameters": [PROJECT_PARAM],
    "dashcards": [
        {
            "id": -1, "card_id": 44,
            "row": 0, "col": 0, "size_x": 24, "size_y": 8,
            "parameter_mappings": [{
                "parameter_id": "project_key_param",
                "card_id": 44,
                "target": ["variable", ["template-tag", "project_key"]]
            }],
            "visualization_settings": {}
        }
    ]
}
```

### Click-through drill-down (Portfolio → Team Workload)

Set `visualization_settings` on the table dashcard:
```python
{
    "click_behavior": {
        "type": "link",
        "linkType": "dashboard",
        "targetId": <target_dashboard_id>,
        "parameterMapping": {
            "project_key_param": {
                "source": {"type": "column", "id": "project_key", "name": "project_key"},
                "target": {"type": "parameter", "id": "project_key_param"},
                "id": "project_key_param"
            }
        }
    }
}
```

**Important**: Create destination dashboards BEFORE the source dashboard so you have the target ID. The `source.id` must exactly match the SQL column alias.

### Full-width dashboard

Always include `"width": "full"` in every `PUT /api/dashboard/{id}` call.

## Existing Dashboards

| ID | Name | URL | Notes |
|----|------|-----|-------|
| 5 | Portfolio Overview | /dashboard/5 | KPI cards + project table, click → Team Workload |
| 6 | Team Workload | /dashboard/6 | Project filter, 3 charts |
| 7 | Sprint Progress | /dashboard/7 | Project filter, status + epic completion |
| 8 | Missing Effort Report | /dashboard/8 | Project filter, issues without worklogs |
| 9 | Historical Trend | /dashboard/9 | Project filter, monthly trends |

Re-run after changes: `python3 metabase/create_dashboards.py`

## Quick API Reference

```bash
# List all questions
curl -s http://localhost:3000/api/card -H "X-Metabase-Session: $SESSION"

# Run a question
curl -s -X POST http://localhost:3000/api/card/{id}/query \
  -H "X-Metabase-Session: $SESSION" -H "Content-Type: application/json" -d '{}'

# Get dashboard
curl -s http://localhost:3000/api/dashboard/{id} -H "X-Metabase-Session: $SESSION"

# Sync DB schema
curl -s -X POST http://localhost:3000/api/database/2/sync_schema -H "X-Metabase-Session: $SESSION"
```

## Common Mistakes to Avoid

1. **Empty description** fails API: either omit `description` or make it non-empty string
2. **Joining dim_issues ↔ fact_worklogs by issue_key returns 0 rows** — different datasets
3. **project_key is NULL in fact_worklogs** — always use `SPLIT_PART(issue_key, '-', 1)`
4. **Parameter mappings** must be in the dashcard, not a separate API call
5. **Create destination dashboards first** when setting up drill-through click behaviors
6. **MCP session init**: POST to `/api/metabase-mcp` with `x-api-key` header (not session token)
