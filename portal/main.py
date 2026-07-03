import os
import io
import csv
import json
import uuid
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

import config
from auth import create_token, get_current_user, LoginRequired

app = FastAPI(title="ppmER Portal")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static", follow_symlink=True), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

DOCKER_SOCK = "/var/run/docker.sock"


# ── CloudBeaver proxy config ─────────────────────────────────────────────────
_CB_URL = os.getenv("CLOUDBEAVER_INTERNAL_URL", "http://cloudbeaver:8978")
_CB_ROOT = "/cb"  # matches CLOUDBEAVER_ROOT_URI in docker-compose
_CB_GQL = f"{_CB_URL}{_CB_ROOT}/api/gql"

# Portal role → CB user credentials
_CB_CREDS: dict[str, tuple[str, str]] = {
    "admin":      (os.getenv("CB_ADMIN_NAME", "cbadmin"),  os.getenv("CB_ADMIN_PASSWORD", "Jppm@min123")),
    "developer":  (os.getenv("CB_ADMIN_NAME", "cbadmin"),  os.getenv("CB_ADMIN_PASSWORD", "Jppm@min123")),
    "power_user": ("cb_power_user", os.getenv("CB_POWER_USER_PASSWORD", "Jppm@min123")),
    "end_user":   ("cb_analyst",    os.getenv("CB_ANALYST_PASSWORD", "Jppm@min123")),
}

_CB_SESSION_COOKIE = "cb-session-id"  # actual cookie name used by CB 24.x

async def _cb_login(role: str) -> str | None:
    """Open a CB session for the given portal role; return cb-session-id value."""
    username, password = _CB_CREDS.get(role, _CB_CREDS["end_user"])
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(_CB_GQL, json={"query": "mutation { openSession { valid } }"})
            await c.post(_CB_GQL, json={"query": f'{{authLogin(provider:"local",credentials:{{user:"{username}",password:"{password}"}},linkUser:false){{authStatus}}}}'})
            return c.cookies.get(_CB_SESSION_COOKIE)
    except Exception:
        return None

_CB_HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "te", "trailers", "upgrade",
                   "content-encoding", "x-frame-options", "content-security-policy",
                   "content-security-policy-report-only"}
ENV_FILE = Path("/run/stack.env")  # mounted .env from host (outside /app to avoid volume conflict)


# ---------------------------------------------------------------------------
# Docker socket helpers
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    return Path(DOCKER_SOCK).exists()


async def _docker(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=30) as client:
        return await getattr(client, method)(path, **kwargs)


def _parse_logs(raw: bytes) -> list[str]:
    """Parse Docker multiplexed log stream (8-byte frame header per line)."""
    lines, i = [], 0
    while i + 8 <= len(raw):
        stream_type = raw[i]
        if stream_type not in (1, 2):
            # Not multiplexed (TTY mode) — decode as plain text
            return raw.decode("utf-8", errors="replace").splitlines()
        size = int.from_bytes(raw[i + 4:i + 8], "big")
        if i + 8 + size > len(raw):
            break
        line = raw[i + 8:i + 8 + size].decode("utf-8", errors="replace").rstrip("\n")
        if line:
            lines.append(line)
        i += 8 + size
    return lines


# ---------------------------------------------------------------------------
# Exception handler: LoginRequired → redirect
# ---------------------------------------------------------------------------
@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=302)


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = config.USERS.get(username)
    if not user or user["password"] != password:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid username or password"}, status_code=401
        )
    token = create_token(username, user["role"])
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie("session", token, httponly=True, max_age=86400)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


# ---------------------------------------------------------------------------
# Main routes
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    return RedirectResponse("/home")


@app.get("/home", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def home(request: Request):
    user = get_current_user(request)
    services = config.get_user_services(user["role"])
    role_label = config.ROLE_LABELS.get(user["role"], user["role"])
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "services": services,
            "role_label": role_label,
            "metabase_url": config.get_service_url("metabase"),
        },
    )


@app.get("/embed/cloudbeaver", response_class=HTMLResponse)
async def embed_cloudbeaver(request: Request):
    user = get_current_user(request)
    if "cloudbeaver" not in config.SERVICES or user["role"] not in config.SERVICES["cloudbeaver"]["roles"]:
        return HTMLResponse("<h1>Access Denied</h1>", status_code=403)
    cb_user, cb_pass = _CB_CREDS.get(user["role"], _CB_CREDS["end_user"])
    session_id = await _cb_login(user["role"])
    resp = templates.TemplateResponse(
        "embed.html",
        {"request": request, "user": user, "service_name": "Database & Query",
         "service_url": "/cb/", "can_embed": True, "service_icon": "🗄️",
         "cb_auto_login": True, "cb_user": cb_user, "cb_pass": cb_pass},
    )
    if session_id:
        resp.set_cookie(_CB_SESSION_COOKIE, session_id, path="/cb/", httponly=True, samesite="lax")
    return resp


@app.api_route("/cb/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def cb_proxy(request: Request, path: str):
    get_current_user(request)  # require portal session for all CB access
    url = f"{_CB_URL}{_CB_ROOT}/{path}"
    fwd_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ("host", "content-length", "transfer-encoding")}
    async with httpx.AsyncClient(timeout=60) as c:
        resp = await c.request(
            method=request.method, url=url, headers=fwd_headers,
            content=await request.body(),
            params=dict(request.query_params),
            follow_redirects=False,
        )
    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _CB_HOP_HEADERS}
    return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)


@app.get("/embed/{service}", response_class=HTMLResponse)
async def embed_service(request: Request, service: str):
    user = get_current_user(request)
    svc_meta = config.SERVICES.get(service)
    if not svc_meta or user["role"] not in svc_meta["roles"]:
        return HTMLResponse("<h1>Access Denied</h1>", status_code=403)
    url = config.get_service_url(service)
    # Pass authenticated user context to agent via URL param (agent trusts this, portal already verified)
    if service == "agent":
        url = f"{url}/?ppm_user={user.get('username', user.get('name','guest')).lower()}"
    can_embed = svc_meta.get("embed", True)
    return templates.TemplateResponse(
        "embed.html",
        {"request": request, "user": user, "service_name": svc_meta["name"], "service_url": url, "can_embed": can_embed, "service_icon": svc_meta.get("icon", "📊")},
    )


# ---------------------------------------------------------------------------
# Metabase Dashboards
# ---------------------------------------------------------------------------
METABASE_URL = os.getenv("METABASE_URL", "http://metabase:3000")


def metabase_session() -> str | None:
    try:
        resp = httpx.post(
            f"{METABASE_URL}/api/session",
            json={
                "username": os.getenv("MB_ADMIN_EMAIL", "admin@jppm.local"),
                "password": os.getenv("MB_ADMIN_PASSWORD", "Jppm@min123"),
            },
            timeout=10,
        )
        return resp.json().get("id") if resp.status_code == 200 else None
    except Exception:
        return None


@app.get("/api/metabase-dashboards")
async def api_metabase_dashboards(request: Request):
    get_current_user(request)
    token = metabase_session()
    if not token:
        return JSONResponse({"dashboards": [], "error": "Metabase connection failed"})
    try:
        resp = httpx.get(
            f"{METABASE_URL}/api/dashboard",
            headers={"X-Metabase-Session": token},
            timeout=10,
        )
        if resp.status_code != 200:
            return JSONResponse({"dashboards": [], "error": "Failed to fetch dashboards"})
        dashboards = []
        for d in resp.json():
            uuid = d.get("public_uuid")
            if not uuid:
                try:
                    pub = httpx.post(
                        f"{METABASE_URL}/api/dashboard/{d['id']}/public_link",
                        headers={"X-Metabase-Session": token},
                        timeout=10,
                    )
                    if pub.status_code == 200:
                        uuid = pub.json().get("uuid")
                except Exception:
                    pass
            dashboards.append({
                "id": d["id"],
                "name": d.get("name", "Unnamed"),
                "description": d.get("description", ""),
                "public_uuid": uuid,
                "collection_id": d.get("collection_id"),
            })
        return JSONResponse({"dashboards": dashboards})
    except Exception as e:
        return JSONResponse({"dashboards": [], "error": str(e)})


@app.get("/dashboards", response_class=HTMLResponse)
async def dashboards_page(request: Request):
    user = get_current_user(request)
    services = config.get_user_services(user["role"])
    role_label = config.ROLE_LABELS.get(user["role"], user["role"])
    return templates.TemplateResponse(
        "dashboards.html",
        {"request": request, "user": user, "services": services, "role_label": role_label,
         "metabase_url": config.get_service_url("metabase")},
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        return RedirectResponse("/dashboard", status_code=302)
    role_label = config.ROLE_LABELS.get(user["role"], user["role"])
    services_config = {k: {**v, "url": config.get_service_url(k)} for k, v in config.SERVICES.items()}
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "role_label": role_label,
            "services_config": services_config,
            "docker_available": _docker_available(),
            "env_file_available": ENV_FILE.exists(),
        },
    )


# ---------------------------------------------------------------------------
# Stats API (any role)
# ---------------------------------------------------------------------------
@app.get("/api/stats")
async def get_stats(request: Request):
    get_current_user(request)
    stats = {"total_projects": 0, "open_issues": 0, "worklogs_hours_this_month": 0, "last_updated": None}
    try:
        import psycopg2
        conn = psycopg2.connect(config.DB_DSN)
        cur = conn.cursor()

        def safe_query(sql, default=0):
            try:
                cur.execute(sql)
                row = cur.fetchone()
                return row[0] if row and row[0] is not None else default
            except Exception:
                conn.rollback()
                return default

        stats["total_projects"] = safe_query("SELECT COUNT(*) FROM core.dim_projects")
        stats["open_issues"] = safe_query("select count(*) from dim_issues di where di.resolution is NULL")
        stats["worklogs_hours_this_month"] = int(safe_query(
            "select SUM(time_spent_person_days) FROM core.fact_worklogs WHERE date_trunc('month', trx_date) >= date_trunc('month', NOW())"
        ))
        last_updated = safe_query("select max(_etl_date) as last_refresh from core.fact_worklogs", default=None)
        stats["last_updated"] = str(last_updated) if last_updated else "N/A"
        cur.close()
        conn.close()
    except Exception:
        pass
    return JSONResponse(stats)


# ---------------------------------------------------------------------------
# Admin API: Docker service management
# ---------------------------------------------------------------------------

@app.get("/api/services")
async def list_services(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not _docker_available():
        return JSONResponse({"error": "Docker socket not available. Mount /var/run/docker.sock"}, status_code=503)
    try:
        resp = await _docker("get", "/containers/json?all=true")
        data = resp.json()
        # Docker returns {"message": "..."} on error, normalize to {"error": "..."}
        if isinstance(data, dict):
            return JSONResponse({"error": data.get("message", "Docker API error")}, status_code=500)
        # Filter only PPM DataStack containers
        ppm_containers = [c for c in data if (
            # Check by container name (PPM prefix)
            any(name.startswith("/ppm") for name in c.get("Names", [])) or
            # Check by compose project label
            c.get("Labels", {}).get("com.docker.compose.project") == "ppmer"
        )]
        return JSONResponse(ppm_containers)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/services/{container_id}/logs")
async def get_container_logs(request: Request, container_id: str, tail: int = 200):
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not _docker_available():
        return JSONResponse({"error": "Docker socket not available"}, status_code=503)
    try:
        resp = await _docker("get", f"/containers/{container_id}/logs?tail={tail}&stdout=true&stderr=true&timestamps=true")
        lines = _parse_logs(resp.content)
        return JSONResponse({"logs": lines})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/services/{container_id}/action/{action}")
async def container_action(request: Request, container_id: str, action: str):
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if action not in ("restart", "start", "stop"):
        return JSONResponse({"error": "invalid action"}, status_code=400)
    if not _docker_available():
        return JSONResponse({"error": "Docker socket not available"}, status_code=503)
    try:
        resp = await _docker("post", f"/containers/{container_id}/{action}")
        return JSONResponse({"ok": resp.status_code in (200, 204, 304)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Admin API: Environment management
# ---------------------------------------------------------------------------

@app.get("/api/env")
async def get_env(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse(config.get_safe_env())


@app.get("/api/env/all")
async def get_all_env(request: Request):
    """Return all env vars including sensitive ones (admin only, reads from mounted .env file)."""
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)

    if ENV_FILE.exists():
        result = {}
        for line in ENV_FILE.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, v = stripped.partition("=")
            result[k.strip()] = v.strip()
        return JSONResponse(result)

    # Fallback: return env from process (sensitive values masked)
    return JSONResponse(config.get_safe_env())


@app.post("/api/env/save")
async def save_env_vars(request: Request):
    """Write updated env vars back to the mounted .env file."""
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not ENV_FILE.exists():
        return JSONResponse({"error": "Env file not mounted at /app/stack.env. Add volume: ./.env:/app/stack.env to portal service."}, status_code=404)

    body = await request.json()
    updates: dict = body.get("vars", {})

    lines = ENV_FILE.read_text().splitlines()
    new_lines, updated = [], set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k = stripped.split("=")[0].strip()
        if k in updates:
            new_lines.append(f"{k}={updates[k]}")
            updated.add(k)
        else:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in updated:
            new_lines.append(f"{k}={v}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n")
    return JSONResponse({"ok": True, "updated": sorted(updated)})



# ---------------------------------------------------------------------------
# Developer routes
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# DB-GPT Chat (AI Assistant) — sessions, insights, export, knowledge base
# ---------------------------------------------------------------------------

DBGPT_URL = os.getenv("DBGPT_INTERNAL_URL", "http://dbgpt:5670")
DBGPT_DB = os.getenv("POSTGRES_DB", "ppm_datawarehouse")
_AGENT_DSN = (
    f"host={os.getenv('DB_HOST', 'postgres')} "
    f"port={os.getenv('DB_PORT', '5432')} "
    f"dbname={os.getenv('AGENT_DB', 'ppmdatastack')} "
    f"user={os.getenv('DB_USER', 'ppm_user')} "
    f"password={os.getenv('DB_PASSWORD', '')}"
)

AVAILABLE_MODELS = [
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "provider": "Google"},
    {"id": "gemini-2.0-flash-lite", "label": "Gemini 2.0 Flash Lite", "provider": "Google"},
    {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash", "provider": "DeepSeek"},
    {"id": "gpt-4o-mini", "label": "GPT-4o Mini", "provider": "OpenAI"},
]


def _agent_conn():
    return psycopg2.connect(_AGENT_DSN)


def _ensure_dbgpt_tables():
    try:
        conn = _agent_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dbgpt_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New Chat',
                    user_name TEXT NOT NULL,
                    model_name TEXT NOT NULL DEFAULT 'gemini-2.5-flash',
                    message_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS dbgpt_messages (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT REFERENCES dbgpt_sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sql_query TEXT,
                    chart_data JSONB,
                    insights TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS user_layouts (
                    username TEXT PRIMARY KEY,
                    layout JSONB NOT NULL DEFAULT '[]',
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
        conn.commit()
        conn.close()
    except Exception:
        pass


_ensure_dbgpt_tables()


async def _generate_insights(user_input: str, sql: str, data: list, model_name: str) -> str:
    """Call Gemini to generate key insights about query results."""
    if not data or len(data) == 0:
        return ""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=os.getenv("GEMINI_API_KEY", ""),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        )
        sample = data[:5]
        prompt = f"""You are a senior PPM analyst reviewing data results.
User asked (respond in the SAME language): "{user_input}"
Query returned {len(data)} rows. Data sample:
{json.dumps(sample, ensure_ascii=False, default=str)}

Write EXACTLY 3 insight bullets. Each bullet has two parts:
1. **Finding** — a concrete observation from the data (1 sentence, with specific numbers/names)
2. **Action** — a specific, actionable recommendation based on that finding (1 sentence)

Output format — EXACTLY 3 lines, each on its own line, nothing else:
🔴 **[observation with data]** → [specific action to take]
📌 **[observation with data]** → [specific action to take]
💡 **[observation with data]** → [specific action to take]

CRITICAL: Each bullet MUST be on a SEPARATE LINE. No introductory text. No paragraph prose. Just the 3 lines above.

Use appropriate emoji: 🔴 for risks, 📌 for important findings, 💡 for opportunities, ⚠️ for warnings, ✅ for positives."""
        # ponytail: gemini-2.5-flash thinking uses ~1200 tokens; set max_tokens high enough for thinking+output
        resp = await client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


def _parse_dbgpt_plan(content: str) -> dict | None:
    """Extract DB-GPT plan JSON ({"thoughts":..., "sql":...}) from raw content or markdown code block."""
    text = content.strip()
    # Strip markdown code fences
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)
        else:
            text = re.sub(r"```[a-z]*", "", text).strip()
    # Find first JSON object in text
    start = text.find("{")
    if start == -1:
        return None
    try:
        return json.loads(text[start:])
    except Exception:
        # Try to find JSON by brace matching
        depth, end = 0, -1
        for i, ch in enumerate(text[start:], start):
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            try:
                return json.loads(text[start:end])
            except Exception:
                pass
    return None


def _extract_chart_data(content: str) -> dict | None:
    """Parse DB-GPT's <chart-view> tag into structured data."""
    if "<chart-view" not in content:
        return None
    try:
        raw = content.split('<chart-view content="')[1].split('"')[0]
        raw = raw.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        return json.loads(raw)
    except Exception:
        return None


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    user = get_current_user(request)
    services = config.get_user_services(user["role"])
    role_label = config.ROLE_LABELS.get(user["role"], user["role"])
    return templates.TemplateResponse(
        "chat.html",
        {"request": request, "user": user, "services": services, "role_label": role_label},
    )


@app.get("/api/dbgpt/models")
async def dbgpt_models(request: Request):
    get_current_user(request)
    return JSONResponse({"models": AVAILABLE_MODELS})


@app.get("/api/dbgpt/sessions")
async def dbgpt_sessions(request: Request):
    user = get_current_user(request)
    try:
        conn = _agent_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, title, model_name, message_count, created_at, updated_at FROM dbgpt_sessions WHERE user_name=%s ORDER BY updated_at DESC LIMIT 50",
                (user["username"],),
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                r["created_at"] = r["created_at"].isoformat()
                r["updated_at"] = r["updated_at"].isoformat()
        conn.close()
        return JSONResponse({"sessions": rows})
    except Exception as e:
        return JSONResponse({"sessions": [], "error": str(e)})


@app.post("/api/dbgpt/sessions")
async def dbgpt_create_session(request: Request):
    user = get_current_user(request)
    body = await request.json()
    sid = str(uuid.uuid4())
    model_name = body.get("model_name", "gemini-2.5-flash")
    try:
        conn = _agent_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO dbgpt_sessions (id, title, user_name, model_name) VALUES (%s, %s, %s, %s)",
                (sid, "New Chat", user["username"], model_name),
            )
        conn.commit()
        conn.close()
        return JSONResponse({"id": sid, "title": "New Chat", "model_name": model_name})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/dbgpt/sessions/{session_id}")
async def dbgpt_delete_session(request: Request, session_id: str):
    user = get_current_user(request)
    try:
        conn = _agent_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dbgpt_sessions WHERE id=%s AND user_name=%s", (session_id, user["username"]))
        conn.commit()
        conn.close()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/dbgpt/sessions/{session_id}/messages")
async def dbgpt_session_messages(request: Request, session_id: str):
    user = get_current_user(request)
    try:
        conn = _agent_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT s.user_name FROM dbgpt_sessions s WHERE s.id=%s", (session_id,)
            )
            row = cur.fetchone()
            if not row or row["user_name"] != user["username"]:
                conn.close()
                return JSONResponse({"error": "not found"}, status_code=404)
            cur.execute(
                "SELECT id, role, content, sql_query, chart_data, insights, created_at FROM dbgpt_messages WHERE session_id=%s ORDER BY id",
                (session_id,),
            )
            msgs = []
            for m in cur.fetchall():
                d = dict(m)
                d["created_at"] = d["created_at"].isoformat()
                msgs.append(d)
        conn.close()
        return JSONResponse({"messages": msgs})
    except Exception as e:
        return JSONResponse({"messages": [], "error": str(e)})


@app.post("/api/dbgpt/chat")
async def dbgpt_chat(request: Request):
    """Proxy chat to DB-GPT, save history, generate insights."""
    user = get_current_user(request)
    body = await request.json()
    user_input = body.get("user_input", "")
    session_id = body.get("session_id") or str(uuid.uuid4())
    model_name = body.get("model_name", os.getenv("LLM_MODEL_NAME", "gemini-2.5-flash"))

    _SYS_HINT = """[PPM Analyst Rules]
- ALWAYS include both _key and _name columns: project_key+project_name, issue_key+summary, user_key+user_name
- For effort/time metrics ALWAYS return BOTH: time_spent_hours AND time_spent_person_days (mandays) in the same query
- Format dates as ISO (YYYY-MM-DD) or YYYY-MM for monthly grouping
- Numeric columns must be labeled clearly (e.g. total_hours, total_mandays, open_issues)
- Choose display_type wisely: response_table for data, bar_chart/line_chart/pie_chart for trends/comparisons
- For trend queries use line_chart; for comparisons use bar_chart; for distributions use pie_chart
- When user asks for a chart, ALWAYS use a chart display_type (not response_table)
- Include enough columns to make the chart meaningful (label + at least one numeric series)
- Schema to use: mart, core, staging (NEVER raw_jira)
"""
    dbgpt_payload = {
        "user_input": _SYS_HINT + "\nUser question: " + user_input,
        "chat_mode": "chat_with_db_execute",
        "select_param": DBGPT_DB,
        "model_name": model_name,
        "incremental": False,
        "conv_uid": session_id,
        "user_name": user.get("username", "portal_user"),
    }

    async def stream_response():
        # Save user message
        try:
            conn = _agent_conn()
            with conn.cursor() as cur:
                # Ensure session exists
                cur.execute(
                    "INSERT INTO dbgpt_sessions (id, title, user_name, model_name) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                    (session_id, user_input[:60] or "New Chat", user["username"], model_name),
                )
                cur.execute(
                    "INSERT INTO dbgpt_messages (session_id, role, content) VALUES (%s, 'user', %s)",
                    (session_id, user_input),
                )
                # Update session title from first message
                cur.execute(
                    "UPDATE dbgpt_sessions SET updated_at=NOW(), message_count=message_count+1, title=CASE WHEN title='New Chat' THEN %s ELSE title END WHERE id=%s",
                    (user_input[:60], session_id),
                )
            conn.commit()
            conn.close()
        except Exception:
            pass

        # Call DB-GPT
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{DBGPT_URL}/api/v1/chat/completions", json=dbgpt_payload)
                if resp.status_code != 200:
                    yield f'data: {{"error": "DB-GPT returned {resp.status_code}"}}\n\n'
                    return

                lines = [l for l in resp.text.splitlines() if l.startswith("data:")]
                final_content = ""
                for line in lines:
                    raw = line[5:].strip()
                    try:
                        d = json.loads(raw)
                        c = d["choices"][0]["message"]["content"]
                        if c and "<span" not in c:
                            final_content = c
                    except Exception:
                        pass
                    yield line + "\n\n"

                chart_data = _extract_chart_data(final_content)
                sql_query = chart_data.get("sql") if chart_data else None
                data_rows = chart_data.get("data", []) if chart_data else []

                # ponytail: DB-GPT returns plan JSON when it fails to execute complex SQL.
                # Portal backend executes the SQL itself and sends a synthetic chart-view event.
                if not chart_data and final_content:
                    plan = _parse_dbgpt_plan(final_content)
                    if plan and plan.get("sql"):
                        sql_query = plan["sql"]
                        display_type = plan.get("display_type", "response_table")
                        agent_thoughts = plan.get("thoughts", "")
                        try:
                            conn = _agent_conn()
                            with conn.cursor() as cur:
                                cur.execute(sql_query)
                                cols = [desc[0] for desc in cur.description]
                                rows = cur.fetchmany(200)
                                data_rows = [dict(zip(cols, r)) for r in rows]
                            conn.close()
                            chart_data = {"type": display_type, "sql": sql_query, "data": data_rows}
                            chart_json = json.dumps(chart_data, ensure_ascii=False, default=str)
                            encoded = chart_json.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
                            synth_content = f'<chart-view content="{encoded}" />'
                            synth_line = json.dumps({"choices": [{"message": {"role": "assistant", "content": synth_content}}]})
                            yield f"data: {synth_line}\n\n"
                            # send thoughts so frontend can display them
                            if agent_thoughts:
                                yield f'data: {json.dumps({"thoughts": agent_thoughts})}\n\n'
                            final_content = synth_content
                        except Exception as exec_err:
                            err_content = f"SQL execution failed: {exec_err}"
                            err_line = json.dumps({"choices": [{"message": {"role": "assistant", "content": err_content}}]})
                            yield f"data: {err_line}\n\n"
                            chart_data = None
                insights = ""
                if data_rows:
                    insights = await _generate_insights(user_input, sql_query or "", data_rows, model_name)

                # Send insights as extra SSE event
                if insights:
                    insights_payload = json.dumps({"insights": insights})
                    yield f"data: {insights_payload}\n\n"

                # Save assistant response
                try:
                    conn = _agent_conn()
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO dbgpt_messages (session_id, role, content, sql_query, chart_data, insights) VALUES (%s, 'assistant', %s, %s, %s, %s)",
                            (session_id, final_content, sql_query, json.dumps(chart_data) if chart_data else None, insights),
                        )
                        cur.execute(
                            "UPDATE dbgpt_sessions SET updated_at=NOW(), message_count=message_count+1 WHERE id=%s",
                            (session_id,),
                        )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

                yield "data: [DONE]\n\n"

        except httpx.ConnectError:
            yield 'data: {"error": "DB-GPT service not available."}\n\n'
        except Exception as e:
            yield f'data: {{"error": "{str(e)}"}}\n\n'

    return StreamingResponse(stream_response(), media_type="text/event-stream")


@app.get("/api/dbgpt/export/{session_id}/{msg_id}")
async def dbgpt_export_csv(request: Request, session_id: str, msg_id: int):
    """Export query results as CSV."""
    user = get_current_user(request)
    try:
        conn = _agent_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT m.chart_data, s.user_name FROM dbgpt_messages m JOIN dbgpt_sessions s ON m.session_id=s.id WHERE m.id=%s AND m.session_id=%s",
                (msg_id, session_id),
            )
            row = cur.fetchone()
        conn.close()
        if not row or row["user_name"] != user["username"]:
            return JSONResponse({"error": "not found"}, status_code=404)
        chart_data = row["chart_data"] or {}
        if isinstance(chart_data, str):
            chart_data = json.loads(chart_data)
        data = chart_data.get("data", [])
        if not data:
            return JSONResponse({"error": "no data"}, status_code=400)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
        writer.writeheader()
        writer.writerows(data)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=ppm_export_{msg_id}.csv"},
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/dbgpt/health")
async def dbgpt_health(request: Request):
    get_current_user(request)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{DBGPT_URL}/api/health")
            return JSONResponse({"status": "ok" if resp.status_code == 200 else "degraded"})
    except Exception as e:
        return JSONResponse({"status": "unavailable", "error": str(e)}, status_code=503)


@app.post("/api/dbgpt/init-datasource")
async def dbgpt_init_datasource(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    payload = {
        "db_type": "postgresql", "db_name": os.getenv("POSTGRES_DB", "ppm_datawarehouse"),
        "db_host": "postgres", "db_port": 5432,
        "db_user": "ppm_ai", "db_pwd": os.getenv("DBGPT_AI_DB_PASS", "ppm_ai_123"),
        "comment": "PPM Data Warehouse",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{DBGPT_URL}/api/v1/chat/db/add", json=payload)
            return JSONResponse({"status": resp.status_code, "body": resp.json()})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/api/query")
async def run_db_query(request: Request):
    """Execute a SELECT query against the data warehouse (read-only)."""
    user = get_current_user(request)
    body = await request.json()
    sql = body.get("sql", "").strip()
    if not sql.upper().startswith("SELECT"):
        return JSONResponse({"error": "Only SELECT queries are allowed"}, status_code=400)
    try:
        conn = psycopg2.connect(config.DB_DSN)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchmany(500)]
        conn.close()
        cols = list(rows[0].keys()) if rows else []
        return Response(
            content=json.dumps({"rows": rows, "columns": cols}, default=str),
            media_type="application/json",
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/layout")
async def get_layout(request: Request):
    user = get_current_user(request)
    try:
        conn = _agent_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT layout FROM user_layouts WHERE username=%s", (user["username"],))
            row = cur.fetchone()
        conn.close()
        return JSONResponse({"layout": row[0] if row else None})
    except Exception as e:
        return JSONResponse({"layout": None, "error": str(e)})


@app.post("/api/layout")
async def save_layout(request: Request):
    user = get_current_user(request)
    body = await request.json()
    widgets = body.get("widgets", [])
    try:
        conn = _agent_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_layouts (username, layout) VALUES (%s, %s) ON CONFLICT (username) DO UPDATE SET layout=%s, updated_at=NOW()",
                (user["username"], json.dumps(widgets), json.dumps(widgets)),
            )
        conn.commit()
        conn.close()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
