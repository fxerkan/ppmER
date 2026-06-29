import os
import httpx
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

import config
from auth import create_token, get_current_user, LoginRequired

app = FastAPI(title="PPM Data Stack Portal")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

DOCKER_SOCK = "/var/run/docker.sock"
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
        {"request": request, "user": user, "services": services, "role_label": role_label},
    )


@app.get("/embed/{service}", response_class=HTMLResponse)
async def embed_service(request: Request, service: str):
    user = get_current_user(request)
    svc_meta = config.SERVICES.get(service)
    if not svc_meta or user["role"] not in svc_meta["roles"]:
        return HTMLResponse("<h1>Access Denied</h1>", status_code=403)
    url = config.get_service_url(service)
    # Pass authenticated user context to agent via URL param (agent trusts this, portal already verified)
    if service == "agent":
        # Pass the username (dict key) so agent can look up user in PORTAL_USERS
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
        {"request": request, "user": user, "services": services, "role_label": role_label},
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

        stats["total_projects"] = safe_query("SELECT COUNT(*) FROM staging.stg_jira__projects")
        stats["open_issues"] = safe_query("SELECT COUNT(*) FROM staging.stg_jira__issues WHERE resolution IS NULL")
        stats["worklogs_hours_this_month"] = int(safe_query(
            "SELECT ROUND(SUM(time_spent_seconds)/3600.0) FROM core.fact_worklogs WHERE date_trunc('month', started_at) = date_trunc('month', NOW())"
        ))
        last_updated = safe_query("SELECT MAX(loaded_at) FROM raw_jira.issues", default=None)
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
            c.get("Labels", {}).get("com.docker.compose.project") == "jira-ppm-data-stack"
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
@app.get("/files", response_class=HTMLResponse)
async def browse_files(request: Request):
    user = get_current_user(request)
    if user["role"] not in ("admin", "developer"):
        return RedirectResponse("/dashboard", status_code=302)

    root = Path(__file__).parent.parent
    dirs = {"dbt/models": [], "dlt": []}
    for rel_dir in dirs:
        p = root / rel_dir
        if p.exists():
            dirs[rel_dir] = sorted(
                str(f.relative_to(root))
                for f in p.rglob("*")
                if f.is_file() and f.suffix in (".sql", ".py", ".yml", ".yaml", ".toml")
            )

    role_label = config.ROLE_LABELS.get(user["role"], user["role"])
    return templates.TemplateResponse(
        "files.html",
        {"request": request, "user": user, "dirs": dirs, "role_label": role_label},
    )


@app.get("/file-content")
async def file_content(request: Request, path: str):
    user = get_current_user(request)
    if user["role"] not in ("admin", "developer"):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    root = Path(__file__).parent.parent
    target = (root / path).resolve()
    if not str(target).startswith(str(root.resolve())):
        return JSONResponse({"error": "path traversal denied"}, status_code=400)
    if not target.exists() or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)

    content = target.read_text(errors="replace")
    return JSONResponse({"path": path, "content": content})
