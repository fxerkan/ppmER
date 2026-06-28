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
    f"host={os.getenv('DB_HOST', 'postgres')} "
    f"port={os.getenv('DB_PORT', '5432')} "
    f"dbname={os.getenv('DB_NAME', 'ppm_datawarehouse')} "
    f"user={os.getenv('DB_USER', 'ppm_user')} "
    f"password={os.getenv('DB_PASSWORD', '')}"
)


def get_service_url(key: str) -> str:
    port_map = {
        "mage": int(os.getenv("MAGE_EXTERNAL_PORT", 6789)),
        "dbt_docs": int(os.getenv("DBT_DOCS_EXTERNAL_PORT", 8081)),
        "metabase": int(os.getenv("METABASE_EXTERNAL_PORT", 3000)),
        "cloudbeaver": int(os.getenv("CLOUDBEAVER_EXTERNAL_PORT", 8978)),
        "upload": int(os.getenv("UPLOAD_EXTERNAL_PORT", 8080)),
        "agent": int(os.getenv("AGENT_PORT", 7860)),
    }
    port = port_map.get(key, 8000)
    return f"http://localhost:{port}"


SERVICES = {
    "mage": {"name": "Orchestration", "icon": "🔄", "roles": ["admin", "developer"], "embed": True},
    "dbt_docs": {"name": "dbt Docs", "icon": "📐", "roles": ["admin", "developer", "power_user"], "embed": True},
    # ponytail: metabase full-app iframe requires Pro; show launch page instead
    "metabase": {"name": "Metabase", "icon": "📊", "roles": ["admin", "developer", "power_user", "end_user"], "embed": False},
    "cloudbeaver": {"name": "CloudBeaver", "icon": "🗄️", "roles": ["admin", "developer"], "embed": True},
    "upload": {"name": "Data Files", "icon": "📁", "roles": ["admin", "developer", "power_user", "end_user"], "embed": True},
    "agent": {"name": "AI Agent", "icon": "🤖", "roles": ["admin", "developer", "power_user", "end_user"], "embed": True},
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
