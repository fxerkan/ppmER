import os

USERS = {
    "admin": {"password": os.getenv("PORTAL_ADMIN_PASS", "Jppm@min123"), "role": "admin", "name": "Admin"},
    "developer": {"password": os.getenv("PORTAL_DEV_PASS", "Jppm@min123"), "role": "developer", "name": "Developer"},
    "analyst": {"password": os.getenv("PORTAL_ANALYST_PASS", "Jppm@min123"), "role": "power_user", "name": "Power User"},
    "user": {"password": os.getenv("PORTAL_USER_PASS", "Jppm@min123"), "role": "end_user", "name": "End User"},
}

ROLE_LABELS = {
    "admin": "Admin",
    "developer": "Developer",
    "power_user": "Power User",
    "end_user": "End User",
}

SECRET_KEY = os.getenv("PORTAL_SECRET_KEY", "ppm-portal-secret-change-in-prod")

# Data warehouse connection (read-only stats)
DB_DSN = (
    f"host={os.getenv('DB_HOST', 'postgres')} "
    f"port={os.getenv('DB_PORT', '5432')} "
    f"dbname={os.getenv('DB_NAME', 'ppm_datawarehouse')} "
    f"user={os.getenv('DB_USER', 'ppm_user')} "
    f"password={os.getenv('DB_PASSWORD', '')}"
)


DBGPT_INTERNAL_URL = os.getenv("DBGPT_INTERNAL_URL", "http://dbgpt:5670")


def get_service_url(key: str) -> str:
    port_map = {
        "mage": int(os.getenv("MAGE_EXTERNAL_PORT", os.getenv("MAGE_PORT", 6789))),
        "dbt_docs": int(os.getenv("DBT_DOCS_EXTERNAL_PORT", 8081)),
        "metabase": int(os.getenv("METABASE_EXTERNAL_PORT", 3000)),
        "cloudbeaver": int(os.getenv("CLOUDBEAVER_EXTERNAL_PORT", 8978)),
        "upload": int(os.getenv("UPLOAD_EXTERNAL_PORT", 8085)),
        "agent": int(os.getenv("AGENT_PORT", 7860)),
        "dbgpt": int(os.getenv("DBGPT_PORT", 5670)),
    }
    port = port_map.get(key, 8000)
    return f"http://localhost:{port}"


SERVICES = {
    "mage": {"name": "Orchestration", "icon": "🔄", "roles": ["admin", "developer", "power_user", "end_user"], "embed": True, "internal": "mage:6789"},
    "dbt_docs": {"name": "dbt Docs", "icon": "📐", "roles": ["admin", "developer", "power_user"], "embed": True, "internal": "dbt-docs:8080"},
    # ponytail: metabase full-app iframe requires Pro; show launch page instead
    "metabase": {"name": "Metabase", "icon": "📊", "roles": ["admin", "developer", "power_user", "end_user"], "embed": False, "internal": "metabase:3000"},
    "cloudbeaver": {"name": "Database & Query", "icon": "🗄️", "roles": ["admin", "developer", "power_user", "end_user"], "embed": True, "internal": "cloudbeaver:8978"},
    "upload": {"name": "Data Files", "icon": "📁", "roles": ["admin", "developer", "power_user", "end_user"], "embed": True, "internal": "upload:8080"},
    "agent": {"name": "AI Agent (legacy)", "icon": "🤖", "roles": ["admin", "developer"], "embed": True, "internal": "agent:7860"},
    "dbgpt": {"name": "AI Assistant", "icon": "🧠", "roles": ["admin", "developer", "power_user", "end_user"], "embed": False, "internal": "dbgpt:5670"},
}


def get_user_services(role: str) -> dict:
    result = {}
    for key, svc in SERVICES.items():
        if role in svc["roles"]:
            result[key] = {**svc, "url": get_service_url(key)}
    return result


SENSITIVE_SUFFIXES = {"PASSWORD", "PASS", "SECRET", "KEY", "TOKEN"}


def is_sensitive(key: str) -> bool:
    ku = key.upper()
    return any(s in ku for s in SENSITIVE_SUFFIXES)


def get_safe_env() -> dict:
    relevant_prefixes = ("POSTGRES_", "MAGE_", "DBT_", "METABASE_", "CLOUDBEAVER_", "AGENT_", "UPLOAD_", "PORTAL_", "JIRA_", "SMTP_", "SHAREPOINT__", "DLT_", "DEEPSEEK_", "CB_", "MB_")
    return {
        k: ("***" if is_sensitive(k) else v)
        for k, v in os.environ.items()
        if any(k.startswith(p) for p in relevant_prefixes)
    }
