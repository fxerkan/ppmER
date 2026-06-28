import os

# Simple user store (replace with DB when needed)
USERS = {
    "admin": {"password": os.getenv("PORTAL_ADMIN_PASS", "admin123"), "role": "admin", "name": "Administrator"},
    "developer": {"password": os.getenv("PORTAL_DEV_PASS", "dev123"), "role": "developer", "name": "Developer"},
    "analyst": {"password": os.getenv("PORTAL_ANALYST_PASS", "analyst123"), "role": "power_user", "name": "Power User"},
    "user": {"password": os.getenv("PORTAL_USER_PASS", "user123"), "role": "end_user", "name": "End User"},
}

ROLE_LABELS = {
    "admin": "Admin",
    "developer": "Developer",
    "power_user": "Power User",
    "end_user": "End User",
}

SECRET_KEY = os.getenv("PORTAL_SECRET_KEY", "ppm-portal-secret-change-in-prod")

DB_DSN = (
    f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')} "
    f"dbname={os.getenv('POSTGRES_DB', 'jira_ppm')} "
    f"user={os.getenv('POSTGRES_USER', 'postgres')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'postgres')}"
)


def get_service_url(key: str) -> str:
    port_map = {
        "mage": int(os.getenv("MAGE_PORT", 6789)),
        "dbt_docs": int(os.getenv("DBT_DOCS_EXTERNAL_PORT", 8081)),
        "metabase": int(os.getenv("METABASE_EXTERNAL_PORT", 3000)),
        "cloudbeaver": int(os.getenv("CLOUDBEAVER_EXTERNAL_PORT", 8978)),
        "upload": int(os.getenv("UPLOAD_EXTERNAL_PORT", 8080)),
        "agent": int(os.getenv("AGENT_PORT", 7860)),
    }
    port = port_map.get(key, 8000)
    return f"http://localhost:{port}"


SERVICES = {
    "mage": {"name": "Mage AI", "icon": "🔄", "roles": ["admin", "developer"]},
    "dbt_docs": {"name": "dbt Docs", "icon": "📐", "roles": ["admin", "developer", "power_user"]},
    "metabase": {"name": "Metabase", "icon": "📊", "roles": ["admin", "developer", "power_user", "end_user"]},
    "cloudbeaver": {"name": "CloudBeaver", "icon": "🗄️", "roles": ["admin", "developer"]},
    "upload": {"name": "Data Files", "icon": "📁", "roles": ["admin", "developer", "power_user", "end_user"]},
    "agent": {"name": "AI Agent", "icon": "🤖", "roles": ["admin", "developer", "power_user", "end_user"]},
}


def get_user_services(role: str) -> dict:
    result = {}
    for key, svc in SERVICES.items():
        if role in svc["roles"]:
            result[key] = {**svc, "url": get_service_url(key)}
    return result


# Env vars to expose in admin (redact passwords)
REDACTED_KEYS = {"PASSWORD", "PASS", "SECRET", "KEY", "TOKEN"}


def get_safe_env() -> dict:
    relevant_prefixes = ("POSTGRES_", "MAGE_", "DBT_", "METABASE_", "CLOUDBEAVER_", "AGENT_", "UPLOAD_", "PORTAL_")
    result = {}
    for k, v in os.environ.items():
        if any(k.startswith(p) for p in relevant_prefixes):
            if any(r in k.upper() for r in REDACTED_KEYS):
                result[k] = "***"
            else:
                result[k] = v
    return result
