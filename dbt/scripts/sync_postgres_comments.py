#!/usr/bin/env python3

import argparse
import os
import re
from pathlib import Path

import psycopg2
import yaml
from psycopg2 import sql


ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
METADATA_FILE = ROOT / "metadata" / "metabase_dictionary.yml"
TARGET_SCHEMAS = {"staging", "core", "mart"}


def load_yaml_documents(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [doc for doc in yaml.safe_load_all(handle) if doc]


def load_dbt_schema_metadata():
    model_metadata = {}

    for path in MODELS_DIR.rglob("*.yml"):
        for document in load_yaml_documents(path):
            for model in document.get("models", []):
                entry = model_metadata.setdefault(
                    model["name"],
                    {
                        "description": None,
                        "columns": {},
                    },
                )
                if model.get("description"):
                    entry["description"] = clean_text(model["description"])
                for column in model.get("columns", []):
                    description = column.get("description")
                    if description:
                        entry["columns"][column["name"]] = clean_text(description)

    return model_metadata


def load_dictionary_metadata():
    payload = {}
    if METADATA_FILE.exists():
        with METADATA_FILE.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    return payload.get("schemas", {}), payload.get("models", {})


def clean_text(value):
    text = str(value).replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_words(name):
    name = name.strip("_")
    if not name:
        return "value"
    return name.replace("_", " ")


def titleize(name):
    return normalize_words(name).title()


def infer_table_description(schema_name, table_name):
    if table_name.startswith("stg_"):
        return f"Staging relation for {normalize_words(table_name[5:])}. Standardizes source fields before core business transformations."
    if table_name.startswith("dim_"):
        return f"Dimension table for {normalize_words(table_name[4:])}. Provides reusable descriptive attributes for PPM analysis."
    if table_name.startswith("fact_"):
        return f"Fact table for {normalize_words(table_name[5:])}. Stores measurable PPM events and effort values for analytics."
    if table_name.startswith("rpt_"):
        return f"Reporting table for {normalize_words(table_name[4:])}. Designed for direct Metabase consumption."
    if table_name.startswith("map_"):
        return f"Bridge table for {normalize_words(table_name[4:])}. Resolves many-to-many or parent-child relationships for analytics."
    if table_name.startswith("mart_") or table_name.startswith("agg_"):
        return f"Business-facing mart table for {normalize_words(table_name.split('_', 1)[1])}. Optimized for dashboard reporting."
    if re.match(r"^\d+_", table_name):
        return f"Data quality check output for {normalize_words(table_name)}. Highlights records that need operational review."
    return f"{schema_name.title()} relation for {normalize_words(table_name)} in the PPM data stack."


def infer_column_description(column_name):
    words = normalize_words(column_name)

    exact = {
        "period": "Reporting period in YYYY-MM format.",
        "trx_date": "Transaction date at day grain.",
        "etl_date": "ETL processing timestamp for this record.",
        "_etl_date": "ETL processing timestamp for this record.",
        "dlt_load_id": "DLT load identifier for lineage tracking.",
        "_dlt_load_id": "DLT load identifier for lineage tracking.",
        "_dlt_id": "DLT record identifier.",
        "project_id": "Unique Jira project identifier.",
        "project_key": "Jira project key.",
        "project_name": "Project name used in reporting.",
        "issue_id": "Unique Jira issue identifier.",
        "issue_key": "Jira issue key.",
        "issue_summary": "Issue summary or title.",
        "author_id": "Unique identifier of the worklog author or employee.",
        "author_name": "Display name of the worklog author or employee.",
        "time_spent_seconds": "Logged effort duration in seconds.",
        "time_spent_hours": "Logged effort duration in hours.",
        "time_spent_person_days": "Logged effort duration in manday units where 1 day = 8 hours.",
        "logged_time_person_day": "Logged effort in manday units where 1 day = 8 hours.",
        "expected_effort_person_days": "Expected working effort in manday units for the date or period.",
        "total_actual_effort_day": "Actual logged effort in manday units for the employee-day combination.",
        "missing_effort_person_days": "Missing effort in manday units calculated as expected effort minus actual effort.",
        "timesheet_entry_percentage": "Timesheet compliance percentage based on actual effort divided by expected effort.",
        "planned_effort": "Planned effort amount for the reporting period.",
        "actual_effort": "Actual effort amount recorded for the reporting period.",
        "variance_hours": "Difference between actual effort and planned effort in hours.",
        "variance_percent": "Percentage variance between actual effort and planned effort.",
        "ratio_capex": "Manual or calculated CAPEX allocation ratio.",
        "ratio_opex": "Manual or calculated OPEX allocation ratio.",
        "adjustment_amount": "Manual effort adjustment amount applied for the project-period.",
        "final_effort": "Final effort amount after business allocation logic.",
        "final_effort_adjusted": "Final effort amount after manual adjustments are applied.",
        "final_effort_capex": "Final CAPEX effort amount after allocation.",
        "final_effort_opex": "Final OPEX effort amount after allocation.",
        "final_effort_inhouse": "Final effort attributed to inhouse workforce.",
        "final_effort_outsource": "Final effort attributed to outsource workforce.",
        "manual_adjustment_amount": "Manual adjustment amount used to override calculated distribution.",
        "capex_effort": "Effort allocated to CAPEX.",
        "opex_effort": "Effort allocated to OPEX.",
        "completion_pct": "Completion percentage for the related entity.",
        "subtask_completion_pct": "Completion percentage for related subtasks.",
        "health_score": "Composite health score derived from project delivery indicators.",
    }
    if column_name in exact:
        return exact[column_name]

    if column_name.endswith("_id"):
        return f"Identifier for {words[:-3]}." if words.endswith(" id") else f"Identifier for {words}."
    if column_name.endswith("_key"):
        return f"Business key for {words[:-4]}." if words.endswith(" key") else f"Business key for {words}."
    if column_name.endswith("_date"):
        return f"Date value for {words[:-5]}." if words.endswith(" date") else f"Date value for {words}."
    if column_name.endswith("_at"):
        return f"Timestamp for {words[:-3]}." if words.endswith(" at") else f"Timestamp for {words}."
    if column_name.startswith("is_"):
        return f"Boolean flag indicating whether {words[3:]} is true."
    if column_name.startswith("has_"):
        return f"Boolean flag indicating whether the record has {words[4:]}."
    if column_name.endswith("_pct") or column_name.endswith("_percentage"):
        return f"Percentage value for {words}."
    if "effort" in column_name:
        return f"Effort measure for {words} used in PPM reporting."
    if "count" in column_name or column_name.startswith("total_"):
        return f"Aggregated measure for {words}."
    return f"{titleize(column_name)} field."


def infer_kpis(table_name, column_names):
    metrics = []
    cols = set(column_names)

    def add(line):
        if line not in metrics:
            metrics.append(line)

    if "missing_effort_person_days" in cols:
        add("Missing effort (manday): sum(missing_effort_person_days).")
    if "expected_effort_person_days" in cols:
        add("Expected effort (manday): sum(expected_effort_person_days).")
    if "total_actual_effort_day" in cols:
        add("Actual effort (manday): sum(total_actual_effort_day).")
    if "time_spent_person_days" in cols:
        add("Total effort (manday): sum(time_spent_person_days).")
    if "logged_time_person_day" in cols:
        add("Total effort (manday): sum(logged_time_person_day).")
    if "time_spent_hours" in cols:
        add("Total effort (hours): sum(time_spent_hours).")
    if "planned_effort" in cols:
        add("Planned effort: sum(planned_effort).")
    if "actual_effort" in cols:
        add("Actual effort: sum(actual_effort).")
    if "variance_hours" in cols:
        add("Effort variance (hours): sum(variance_hours).")
    if "variance_percent" in cols:
        add("Effort variance (%): avg(variance_percent).")
    if "completion_pct" in cols:
        add("Completion rate (%): avg(completion_pct).")
    if "timesheet_entry_percentage" in cols:
        add("Timesheet entry rate (%): avg(timesheet_entry_percentage).")
    if "ratio_capex" in cols:
        add("CAPEX ratio: avg(ratio_capex).")
    if "ratio_opex" in cols:
        add("OPEX ratio: avg(ratio_opex).")
    if "capex_effort" in cols:
        add("CAPEX effort (manday): sum(capex_effort).")
    if "opex_effort" in cols:
        add("OPEX effort (manday): sum(opex_effort).")
    if "final_effort" in cols:
        add("Final effort (manday): sum(final_effort).")
    if "final_effort_adjusted" in cols:
        add("Adjusted final effort (manday): sum(final_effort_adjusted).")
    if "final_effort_capex" in cols:
        add("Final CAPEX effort (manday): sum(final_effort_capex).")
    if "final_effort_opex" in cols:
        add("Final OPEX effort (manday): sum(final_effort_opex).")
    if "final_effort_inhouse" in cols:
        add("Final inhouse effort (manday): sum(final_effort_inhouse).")
    if "final_effort_outsource" in cols:
        add("Final outsource effort (manday): sum(final_effort_outsource).")
    if "adjustment_amount" in cols:
        add("Manual adjustment (manday): sum(adjustment_amount).")
    if "manual_adjustment_amount" in cols:
        add("Manual adjustment (manday): sum(manual_adjustment_amount).")
    if "health_score" in cols:
        add("Health score: avg(health_score).")
    if "project_id" in cols:
        add("Project count: count(distinct project_id).")
    if "issue_id" in cols:
        add("Issue count: count(distinct issue_id).")
    if "author_id" in cols:
        add("Resource count: count(distinct author_id).")
    if "worklog_id" in cols:
        add("Worklog count: count(worklog_id).")

    if table_name.startswith("01_") or table_name.startswith("02_"):
        add("Exception count: count(*).")

    return metrics


def render_table_comment(schema_name, table_name, model_doc, extra_doc, column_names):
    description = (
        (model_doc or {}).get("description")
        or (extra_doc or {}).get("description")
        or infer_table_description(schema_name, table_name)
    )
    kpis = []
    metrics = []

    if extra_doc:
        kpis.extend(extra_doc.get("kpis", []))
        metrics.extend(extra_doc.get("metrics", []))

    for metric in infer_kpis(table_name, column_names):
        if metric not in kpis and metric not in metrics:
            kpis.append(metric)

    parts = [description]
    if kpis:
        parts.append("Primary KPI & Metrics:\n- " + "\n- ".join(kpis))
    if metrics:
        parts.append("Additional Metrics:\n- " + "\n- ".join(metrics))

    return clean_text("\n\n".join(parts))


def get_connection(args):
    return psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )


def fetch_relations(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema IN ('staging', 'core', 'mart')
            ORDER BY table_schema, table_name
            """
        )
        relations = cur.fetchall()

        cur.execute(
            """
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE table_schema IN ('staging', 'core', 'mart')
            ORDER BY table_schema, table_name, ordinal_position
            """
        )
        columns = {}
        for schema_name, table_name, column_name in cur.fetchall():
            columns.setdefault((schema_name, table_name), []).append(column_name)

    return relations, columns


def apply_comments(conn, schema_docs, dbt_docs, dictionary_docs, dry_run=False):
    relations, relation_columns = fetch_relations(conn)
    summary = {"schemas": 0, "tables": 0, "columns": 0}

    with conn.cursor() as cur:
        for schema_name in sorted(TARGET_SCHEMAS):
            schema_comment = schema_docs.get(schema_name)
            if not schema_comment:
                continue
            if not dry_run:
                cur.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS %s").format(sql.Identifier(schema_name)),
                    [schema_comment],
                )
            summary["schemas"] += 1

        for schema_name, table_name, table_type in relations:
            model_doc = dbt_docs.get(table_name, {})
            extra_doc = dictionary_docs.get(table_name, {})
            column_names = relation_columns.get((schema_name, table_name), [])
            table_comment = render_table_comment(
                schema_name,
                table_name,
                model_doc,
                extra_doc,
                column_names,
            )

            object_keyword = "VIEW" if table_type == "VIEW" else "TABLE"
            if not dry_run:
                cur.execute(
                    sql.SQL("COMMENT ON {} {}.{} IS %s").format(
                        sql.SQL(object_keyword),
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                    ),
                    [table_comment],
                )
            summary["tables"] += 1

            column_docs = model_doc.get("columns", {})
            extra_columns = extra_doc.get("columns", {}) if extra_doc else {}
            for column_name in column_names:
                column_comment = (
                    column_docs.get(column_name)
                    or extra_columns.get(column_name)
                    or infer_column_description(column_name)
                )
                if not dry_run:
                    cur.execute(
                        sql.SQL("COMMENT ON COLUMN {}.{}.{} IS %s").format(
                            sql.Identifier(schema_name),
                            sql.Identifier(table_name),
                            sql.Identifier(column_name),
                        ),
                        [clean_text(column_comment)],
                    )
                summary["columns"] += 1

    if not dry_run:
        conn.commit()
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="Sync dbt and KPI descriptions into Postgres comments.")
    parser.add_argument("--host", default=os.getenv("POSTGRES_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("POSTGRES_DB", "ppm_datawarehouse"))
    parser.add_argument("--user", default=os.getenv("POSTGRES_USER", "ppm_user"))
    parser.add_argument("--password", default=os.getenv("POSTGRES_PASSWORD", ""))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    dbt_docs = load_dbt_schema_metadata()
    schema_docs, dictionary_docs = load_dictionary_metadata()

    with get_connection(args) as conn:
        summary = apply_comments(conn, schema_docs, dbt_docs, dictionary_docs, dry_run=args.dry_run)

    print(
        f"Synced comments for {summary['schemas']} schemas, {summary['tables']} relations, and {summary['columns']} columns."
    )


if __name__ == "__main__":
    main()
