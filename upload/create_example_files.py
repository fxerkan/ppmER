"""Generate example Excel files for the upload service demo."""
from pathlib import Path
import pandas as pd

OUT = Path(__file__).parent / "example_files"
OUT.mkdir(exist_ok=True)


def capex_opex_mapping():
    data = [
        ("Bug",              "OPEX",  "Maintenance",     "Operational maintenance work"),
        ("Story",            "CAPEX", "New Development",  "New feature development"),
        ("Task",             "CAPEX", "New Development",  "Development task"),
        ("Epic",             "CAPEX", "New Development",  "Epic-level planning"),
        ("Sub-task",         "CAPEX", "New Development",  "Sub-task of parent"),
        ("Spike",            "OPEX",  "Research",         "Research and investigation"),
        ("Technical Debt",   "OPEX",  "Maintenance",     "Tech debt remediation"),
        ("Incident",         "OPEX",  "Support",          "Production incident handling"),
        ("Change Request",   "CAPEX", "Enhancement",      "Approved change requests"),
        ("Test",             "OPEX",  "Quality",          "Testing activities"),
        ("Documentation",   "OPEX",  "Maintenance",     "Documentation updates"),
        ("Infrastructure",  "CAPEX", "Platform",         "Infrastructure investments"),
        ("Security",         "CAPEX", "Compliance",       "Security compliance work"),
        ("Migration",        "CAPEX", "Platform",         "Data/system migrations"),
        ("Training",         "OPEX",  "Support",          "Training and onboarding"),
    ]
    df = pd.DataFrame(data, columns=["issue_type", "classification", "sub_classification", "notes"])
    df.to_excel(OUT / "capex_opex_mapping.xlsx", index=False)
    print(f"Created capex_opex_mapping.xlsx ({len(df)} rows)")


def calculation_periods():
    import datetime
    rows = []
    for year in [2025, 2026]:
        for month in range(1, 7):
            start = datetime.date(year, month, 1)
            if month == 12:
                end = datetime.date(year, 12, 31)
            else:
                end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
            code = f"{year}M{month:02d}"
            name = start.strftime("%B %Y")
            rows.append((code, name, start.isoformat(), end.isoformat(), year, month <= 3 and year == 2025))
    df = pd.DataFrame(rows, columns=["period_code", "period_name", "start_date", "end_date", "fiscal_year", "is_active"])
    df.to_excel(OUT / "calculation_periods.xlsx", index=False)
    print(f"Created calculation_periods.xlsx ({len(df)} rows)")


def project_budget():
    rows = [
        ("PROJECT-A", "Core Platform Modernization",  2_500_000, "USD", 2025, 80, 20, "CTO",         "2024-11-15"),
        ("PROJECT-B", "Mobile Banking App v2",         1_800_000, "USD", 2025, 90, 10, "CPO",         "2024-12-01"),
        ("PROJECT-C", "Data Lake Infrastructure",      3_200_000, "USD", 2025, 75, 25, "CTO",         "2024-11-20"),
        ("PROJECT-D", "Compliance & Audit Automation", 950_000,   "USD", 2025, 60, 40, "CFO",         "2024-12-10"),
        ("PROJECT-E", "Customer Portal Upgrade",       1_100_000, "USD", 2025, 85, 15, "CPO",         "2025-01-05"),
        ("PROJECT-F", "API Gateway Consolidation",    750_000,   "USD", 2025, 70, 30, "CTO",         "2025-01-10"),
        ("PROJECT-G", "BI & Reporting Suite",          600_000,   "USD", 2025, 65, 35, "CFO",         "2025-01-15"),
        ("PROJECT-H", "Security Hardening Program",   450_000,   "USD", 2025, 55, 45, "CISO",        "2025-01-20"),
        ("PROJECT-I", "DevOps Platform Migration",    1_400_000, "USD", 2026, 80, 20, "CTO",         "2025-03-01"),
        ("PROJECT-J", "ERP Integration Layer",        2_100_000, "USD", 2026, 72, 28, "CFO",         "2025-03-15"),
    ]
    df = pd.DataFrame(rows, columns=[
        "project_key", "project_name", "budget_amount", "currency",
        "fiscal_year", "capex_pct", "opex_pct", "approved_by", "approved_date"
    ])
    df.to_excel(OUT / "project_budget.xlsx", index=False)
    print(f"Created project_budget.xlsx ({len(df)} rows)")


if __name__ == "__main__":
    capex_opex_mapping()
    calculation_periods()
    project_budget()
    print("Done. Files in:", OUT)
