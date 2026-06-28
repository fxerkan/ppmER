import subprocess
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import config
from auth import create_token, get_current_user, LoginRequired

app = FastAPI(title="PPM Data Stack Portal")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


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
    return RedirectResponse("/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
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
    return templates.TemplateResponse(
        "embed.html",
        {"request": request, "user": user, "service_name": svc_meta["name"], "service_url": url},
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        return RedirectResponse("/dashboard", status_code=302)
    env_vars = config.get_safe_env()
    role_label = config.ROLE_LABELS.get(user["role"], user["role"])
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "user": user, "env_vars": env_vars, "role_label": role_label},
    )


# ---------------------------------------------------------------------------
# Admin API routes
# ---------------------------------------------------------------------------
@app.get("/api/docker-status")
async def docker_status(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=10
        )
        containers = []
        for line in result.stdout.strip().splitlines():
            if line:
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return JSONResponse(containers)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/env")
async def get_env(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse(config.get_safe_env())


@app.get("/api/stats")
async def get_stats(request: Request):
    get_current_user(request)  # require auth, any role
    stats = {
        "total_projects": 0,
        "open_issues": 0,
        "worklogs_hours_this_month": 0,
        "last_updated": None,
    }
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
        pass  # Return zeros if DB not available
    return JSONResponse(stats)


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
    # Safety: must be inside repo root
    if not str(target).startswith(str(root.resolve())):
        return JSONResponse({"error": "path traversal denied"}, status_code=400)
    if not target.exists() or not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)

    content = target.read_text(errors="replace")
    return JSONResponse({"path": path, "content": content})
