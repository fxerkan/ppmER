import io, os, re, json
from pathlib import Path
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

import auth
from auth import LoginRequired

load_dotenv()

app = FastAPI(title="Data File Manager")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

EXAMPLE_FILES_DIR = Path(__file__).parent / "example_files"

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "15432")),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}

MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
    "json": "application/json",
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS uploads;

        CREATE TABLE IF NOT EXISTS uploads.file_registry (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            display_name VARCHAR(255) NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            created_by VARCHAR(100) DEFAULT 'anonymous'
        );

        CREATE TABLE IF NOT EXISTS uploads.file_versions (
            id SERIAL PRIMARY KEY,
            file_id INTEGER REFERENCES uploads.file_registry(id),
            version INTEGER NOT NULL,
            original_filename VARCHAR(500),
            file_size_bytes INTEGER,
            row_count INTEGER,
            column_count INTEGER,
            target_table VARCHAR(255),
            status VARCHAR(50) DEFAULT 'active',
            uploaded_at TIMESTAMPTZ DEFAULT NOW(),
            uploaded_by VARCHAR(100) DEFAULT 'anonymous',
            notes TEXT
        );
    """)
    # Safe migrations for new columns
    for sql in [
        "ALTER TABLE uploads.file_versions ADD COLUMN IF NOT EXISTS file_content BYTEA",
        "ALTER TABLE uploads.file_versions ADD COLUMN IF NOT EXISTS file_type VARCHAR(20)",
    ]:
        cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()


@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        print(f"DB init warning: {e}")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=302)


# ── Auth routes ──────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # If already logged in, go home
    try:
        auth.get_current_user(request)
        return RedirectResponse("/", status_code=302)
    except LoginRequired:
        pass
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = auth.USERS.get(username)
    if not user or user["password"] != password:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid username or password"}, status_code=401
        )
    token = auth.create_token(username, user["role"])
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie("session", token, httponly=True, max_age=86400)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


def clean_col(name: str) -> str:
    name = str(name).lower().strip()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "col"


def parse_file(contents: bytes, filename: str, csv_delimiter: str = ",") -> list:
    """Returns list of (suffix, df, json_cols_set)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "json":
        data = json.loads(contents)
        if not isinstance(data, list):
            data = [data]
        rows, json_cols = [], set()
        for item in data:
            row = {}
            for k, v in item.items():
                col = clean_col(k)
                if isinstance(v, (dict, list)):
                    row[col] = json.dumps(v, ensure_ascii=False)
                    json_cols.add(col)
                else:
                    row[col] = v
            rows.append(row)
        return [("", pd.DataFrame(rows), json_cols)]

    if ext == "csv":
        df = pd.read_csv(io.BytesIO(contents), sep=csv_delimiter)
        df.columns = [clean_col(c) for c in df.columns]
        return [("", df, set())]

    # Excel (xlsx/xls)
    sheets = pd.read_excel(io.BytesIO(contents), sheet_name=None)
    if len(sheets) == 1:
        df = list(sheets.values())[0]
        df.columns = [clean_col(c) for c in df.columns]
        return [("", df, set())]
    result = []
    for sheet_name, df in sheets.items():
        df.columns = [clean_col(c) for c in df.columns]
        suffix = "__" + re.sub(r"[^a-z0-9]+", "_", sheet_name.lower()).strip("_")
        result.append((suffix, df, set()))
    return result


def df_to_postgres(df: pd.DataFrame, table: str, conn, json_cols: set = None):
    json_cols = json_cols or set()
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
    cols = df.columns.tolist()
    col_defs = ", ".join(
        f'"{c}" JSONB' if c in json_cols else f'"{c}" TEXT'
        for c in cols
    )
    cur.execute(f'CREATE TABLE {table} ({col_defs})')
    rows = [
        tuple(str(v) if v is not None and str(v) != "nan" else None for v in row)
        for row in df.itertuples(index=False)
    ]
    if rows:
        template = "(" + ", ".join(
            "%s::jsonb" if c in json_cols else "%s" for c in cols
        ) + ")"
        execute_values(cur, f'INSERT INTO {table} VALUES %s', rows, template=template)
    conn.commit()
    cur.close()


def get_or_create_file(conn, name, display_name, description, created_by) -> int:
    cur = conn.cursor()
    cur.execute("SELECT id FROM uploads.file_registry WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        cur.close()
        return row[0]
    cur.execute(
        "INSERT INTO uploads.file_registry (name, display_name, description, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
        (name, display_name, description, created_by)
    )
    file_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return file_id


def next_version(conn, file_id: int) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(version), 0) FROM uploads.file_versions WHERE file_id = %s", (file_id,))
    v = cur.fetchone()[0] + 1
    cur.close()
    return v


def do_upload(contents: bytes, original_filename: str, name: str, display_name: str,
              description: str, uploader: str, notes: str, activate: bool = True,
              csv_delimiter: str = ",") -> dict:
    sheets = parse_file(contents, original_filename, csv_delimiter)
    file_type = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "unknown"
    conn = get_conn()

    file_id = get_or_create_file(conn, name, display_name, description, uploader)
    version = next_version(conn, file_id)

    for suffix, df, json_cols in sheets:
        df_to_postgres(df, f"uploads.{name}_v{version}{suffix}", conn, json_cols)

    primary_suffix = sheets[0][0]
    target_table = f"uploads.{name}_v{version}{primary_suffix}"
    total_rows = sum(len(df) for _, df, _ in sheets)
    total_cols = max(len(df.columns) for _, df, _ in sheets)

    cur = conn.cursor()
    cur.execute("UPDATE uploads.file_versions SET status='archived' WHERE file_id=%s", (file_id,))
    cur.execute("""
        INSERT INTO uploads.file_versions
            (file_id, version, original_filename, file_size_bytes, row_count, column_count,
             target_table, status, uploaded_by, notes, file_content, file_type)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (file_id, version, original_filename, len(contents), total_rows, total_cols,
          target_table, 'active', uploader, notes, psycopg2.Binary(contents), file_type))
    version_id = cur.fetchone()[0]
    conn.commit()
    cur.close()

    if activate:
        for suffix, df, json_cols in sheets:
            df_to_postgres(df, f"uploads.{name}{suffix}", conn, json_cols)

    conn.close()
    return {"file_id": file_id, "version_id": version_id, "version": version,
            "rows": total_rows, "sheets": len(sheets)}


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = auth.get_current_user(request)
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.id, r.name, r.display_name, r.description, r.created_by,
                   v.version, v.row_count, v.uploaded_at, v.uploaded_by, v.file_type
            FROM uploads.file_registry r
            LEFT JOIN uploads.file_versions v ON v.file_id = r.id AND v.status = 'active'
            ORDER BY r.id
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()
        files = [
            {"id": r[0], "name": r[1], "display_name": r[2], "description": r[3],
             "created_by": r[4], "version": r[5], "row_count": r[6],
             "uploaded_at": r[7].strftime("%Y-%m-%d %H:%M") if r[7] else "-",
             "uploaded_by": r[8] or "-", "file_type": r[9] or ""}
            for r in rows
        ]
    except Exception as e:
        files = []
        print(f"DB error: {e}")
    return templates.TemplateResponse("index.html", {"request": request, "files": files, "user": user})


@app.get("/files/{file_id}", response_class=HTMLResponse)
def file_detail(request: Request, file_id: int):
    user = auth.get_current_user(request)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, display_name, description, created_by, created_at FROM uploads.file_registry WHERE id=%s", (file_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return HTMLResponse("File not found", status_code=404)
    file = {"id": row[0], "name": row[1], "display_name": row[2], "description": row[3],
            "created_by": row[4], "created_at": row[5].strftime("%Y-%m-%d %H:%M") if row[5] else "-"}

    cur.execute("""
        SELECT id, version, original_filename, row_count, column_count, uploaded_by,
               uploaded_at, status, notes, target_table, file_type,
               (file_content IS NOT NULL) as has_content
        FROM uploads.file_versions WHERE file_id=%s ORDER BY version DESC
    """, (file_id,))
    versions = [
        {"id": r[0], "version": r[1], "original_filename": r[2], "row_count": r[3],
         "column_count": r[4], "uploaded_by": r[5],
         "uploaded_at": r[6].strftime("%Y-%m-%d %H:%M") if r[6] else "-",
         "status": r[7], "notes": r[8], "target_table": r[9],
         "file_type": r[10] or "", "has_content": r[11]}
        for r in cur.fetchall()
    ]

    cur.close(); conn.close()
    return templates.TemplateResponse("file_detail.html", {
        "request": request, "file": file, "versions": versions, "user": user,
    })


@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    display_name: str = Form(...),
    description: str = Form(""),
    notes: str = Form(""),
    csv_delimiter: str = Form(","),
):
    user = auth.get_current_user(request)
    contents = await file.read()
    name = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    try:
        result = do_upload(contents, file.filename, name, display_name, description,
                           user["username"], notes, csv_delimiter=csv_delimiter)
        return RedirectResponse(url=f"/files/{result['file_id']}?success=1", status_code=303)
    except Exception as e:
        return HTMLResponse(f"Upload failed: {e}", status_code=500)


@app.get("/download/{version_id}")
def download(request: Request, version_id: int):
    auth.get_current_user(request)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT original_filename, file_content FROM uploads.file_versions WHERE id=%s", (version_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row or row[1] is None:
        return JSONResponse({"error": "File not stored"}, status_code=404)
    filename, content = row[0], bytes(row[1])
    ext = filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else "bin"
    return Response(
        content,
        media_type=MEDIA_TYPES.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/activate/{version_id}")
def activate_version(request: Request, version_id: int):
    auth.get_current_user(request)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT fv.file_id, fv.target_table, fv.version, fv.file_content, fv.file_type,
               fv.original_filename, fr.name
        FROM uploads.file_versions fv
        JOIN uploads.file_registry fr ON fr.id = fv.file_id
        WHERE fv.id=%s
    """, (version_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return JSONResponse({"error": "Version not found"}, status_code=404)
    file_id, target_table, version_num, content, file_type, orig_filename, name = row

    # Find all sheet tables for this version (handles multi-sheet)
    cur.execute("""
        SELECT table_schema || '.' || table_name
        FROM information_schema.tables
        WHERE table_schema = 'uploads' AND table_name ~ %s
    """, (f"^{re.escape(name)}_v{version_num}(_|$)",))
    versioned_tables = [r[0] for r in cur.fetchall()]

    for vt in versioned_tables:
        suffix = vt.replace(f"uploads.{name}_v{version_num}", "")
        canonical = f"uploads.{name}{suffix}"
        cur.execute(f"DROP TABLE IF EXISTS {canonical}")
        cur.execute(f"CREATE TABLE {canonical} AS SELECT * FROM {vt}")

    cur.execute("UPDATE uploads.file_versions SET status='archived' WHERE file_id=%s", (file_id,))
    cur.execute("UPDATE uploads.file_versions SET status='active' WHERE id=%s", (version_id,))
    conn.commit()
    cur.close(); conn.close()

    return RedirectResponse(url=f"/files/{file_id}?activated=1", status_code=303)


@app.get("/preview/{version_id}")
def preview(request: Request, version_id: int):
    auth.get_current_user(request)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT fv.target_table, fv.version, fr.name
        FROM uploads.file_versions fv
        JOIN uploads.file_registry fr ON fr.id = fv.file_id
        WHERE fv.id=%s
    """, (version_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return JSONResponse({"error": "Not found"}, status_code=404)

    target_table, version_num, name = row

    # Discover all sheet tables for this version
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'uploads' AND table_name ~ %s
        ORDER BY table_name
    """, (f"^{re.escape(name)}_v{version_num}(_|$)",))
    all_table_names = [r[0] for r in cur.fetchall()]

    sheets = []
    for tname in all_table_names:
        suffix = tname[len(f"{name}_v{version_num}"):]
        sheet_label = suffix.lstrip("_") or "Sheet"
        full_table = f"uploads.{tname}"
        try:
            cur.execute(f"SELECT * FROM {full_table} LIMIT 50")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            sheets.append({"label": sheet_label, "columns": cols, "rows": rows})
        except Exception as e:
            sheets.append({"label": sheet_label, "error": str(e)})

    cur.close(); conn.close()
    return JSONResponse({"sheets": sheets})


@app.get("/load-examples")
def load_examples(request: Request):
    auth.get_current_user(request)
    results = []
    for f in sorted(EXAMPLE_FILES_DIR.glob("*.xlsx")):
        name = f.stem
        display_name = name.replace("_", " ").title()
        try:
            contents = f.read_bytes()
            r = do_upload(contents, f.name, name, display_name, f"Example file: {display_name}", "system", "Auto-loaded example")
            results.append({"file": f.name, "status": "ok", **r})
        except Exception as e:
            results.append({"file": f.name, "status": "error", "error": str(e)})
    return JSONResponse(results)
