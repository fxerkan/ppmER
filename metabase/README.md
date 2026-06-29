# Metabase Dashboard Setup

Metabase auto-configures on first start via the `ppm-metabase-setup` container:
- Admin user `admin@jppm.local` / `Jppm@min123` is auto-created (skips setup wizard)
- The `PPM Data Warehouse` database connection is pre-configured

Change credentials in `.env` (`MB_ADMIN_EMAIL`, `MB_ADMIN_PASSWORD`) before production.

After the stack is up, open http://localhost:3000 and log in with admin credentials.

---

## Dashboard 1: Portfolio Overview

**Purpose**: High-level view of all projects.

```sql
SELECT
    p.project_key,
    p.project_name,
    COUNT(DISTINCT i.issue_key) AS total_issues,
    COUNT(DISTINCT CASE WHEN i.status_category != 'Done' THEN i.issue_key END) AS open_issues,
    COUNT(DISTINCT CASE WHEN i.status_category = 'Done' THEN i.issue_key END) AS closed_issues,
    ROUND(SUM(w.time_spent_hours)::numeric, 1) AS total_logged_hours
FROM core.dim_projects p
LEFT JOIN core.dim_issues i ON p.project_key = i.project_key
LEFT JOIN core.fact_worklogs w ON i.issue_key = w.issue_key
GROUP BY p.project_key, p.project_name
ORDER BY total_logged_hours DESC NULLS LAST;
```

---

## Dashboard 2: Team Workload

**Purpose**: Hours per user per week to spot overload and gaps.

```sql
-- Weekly hours per user (last 12 weeks)
SELECT
    u.display_name,
    DATE_TRUNC('week', w.trx_date) AS week_start,
    ROUND(SUM(w.time_spent_hours)::numeric, 1) AS hours_logged
FROM core.fact_worklogs w
JOIN core.dim_users u ON w.author_id = u.user_id
WHERE w.trx_date >= CURRENT_DATE - INTERVAL '12 weeks'
GROUP BY u.display_name, DATE_TRUNC('week', w.trx_date)
ORDER BY week_start DESC, hours_logged DESC;
```

```sql
-- Top 10 users by total logged hours this month
SELECT
    u.display_name,
    u.email,
    ROUND(SUM(w.time_spent_hours)::numeric, 1) AS hours_this_month
FROM core.fact_worklogs w
JOIN core.dim_users u ON w.author_id = u.user_id
WHERE DATE_TRUNC('month', w.trx_date) = DATE_TRUNC('month', CURRENT_DATE)
GROUP BY u.display_name, u.email
ORDER BY hours_this_month DESC
LIMIT 10;
```

---

## Dashboard 3: Sprint Progress

**Purpose**: Issue status breakdown per project.

```sql
-- Issues by status category per project
SELECT
    i.project_key,
    i.status_category,
    i.status_name,
    COUNT(*) AS issue_count
FROM core.dim_issues i
WHERE i.is_subtask = false
GROUP BY i.project_key, i.status_category, i.status_name
ORDER BY i.project_key, i.status_category;
```

```sql
-- Epic progress: completion percentage
SELECT
    i.project_key,
    i.epic_name,
    COUNT(*) AS total_issues,
    COUNT(CASE WHEN i.status_category = 'Done' THEN 1 END) AS done_issues,
    ROUND(
        100.0 * COUNT(CASE WHEN i.status_category = 'Done' THEN 1 END) / NULLIF(COUNT(*), 0),
        1
    ) AS completion_pct
FROM core.dim_issues i
WHERE i.epic_name IS NOT NULL
  AND i.is_subtask = false
GROUP BY i.project_key, i.epic_name
ORDER BY completion_pct ASC;
```

---

## Dashboard 4: Missing Effort Report

**Purpose**: Find issues that should have logged hours but don't.

```sql
-- Issues with no worklogs (open, assigned, older than 7 days)
SELECT
    i.project_key,
    i.issue_key,
    i.issue_summary,
    i.issue_type,
    i.assignee_name,
    i.status_name,
    i.created_date::date AS created_date,
    CURRENT_DATE - i.created_date::date AS age_days
FROM core.dim_issues i
LEFT JOIN core.fact_worklogs w ON i.issue_key = w.issue_key
WHERE w.issue_key IS NULL
  AND i.status_category NOT IN ('Done')
  AND i.is_subtask = false
  AND i.issue_type NOT IN ('Epic')
  AND i.created_date < CURRENT_DATE - INTERVAL '7 days'
ORDER BY age_days DESC;
```

```sql
-- Or use the pre-built mart model if available
SELECT * FROM mart.rpt_missing_effort
ORDER BY age_days DESC
LIMIT 100;
```

---

## Dashboard 5: Historical Trend

**Purpose**: Issue creation and resolution velocity over time.

```sql
-- Monthly issue creation vs resolution trend
SELECT
    DATE_TRUNC('month', i.created_date) AS month,
    COUNT(*) AS issues_created,
    COUNT(CASE WHEN i.status_category = 'Done' THEN 1 END) AS issues_resolved,
    COUNT(*) - COUNT(CASE WHEN i.status_category = 'Done' THEN 1 END) AS backlog_delta
FROM core.dim_issues i
WHERE i.is_subtask = false
  AND i.issue_type NOT IN ('Epic')
  AND i.created_date >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', i.created_date)
ORDER BY month;
```

```sql
-- Cumulative worklog hours over time
SELECT
    DATE_TRUNC('month', w.trx_date) AS month,
    ROUND(SUM(w.time_spent_hours)::numeric, 1) AS hours_logged,
    COUNT(DISTINCT w.issue_key) AS issues_worked
FROM core.fact_worklogs w
WHERE w.trx_date >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', w.trx_date)
ORDER BY month;
```

---

## Scripts

- `create_dashboards.py` — auto-creates all dashboards via Metabase API
- `dashboards/dashboard_definitions.json` — exported dashboard definitions

Run the script to recreate or update:
```bash
python3 metabase/create_dashboards.py
```

## Tips

- Use **Metabase Questions** (not SQL directly) for interactive filtering
- Add date filters to all dashboards so users can drill into time ranges
- Pin the Portfolio Overview dashboard as the home page
- Set up email subscriptions for the Missing Effort report (weekly digest)
