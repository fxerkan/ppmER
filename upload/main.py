import os, re, json
from pathlib import Path
from typing import Optional
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

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
    conn.commit()
    cur.close()
    conn.close()


@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        print(f"DB init warning: {e}")


def clean_col(name: str) -> str:
    name = str(name).lower().strip()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "col"


def parse_file(contents: bytes, filename: str) -> pd.DataFrame:
    import io
    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(contents))
    else:
        df = pd.read_excel(io.BytesIO(contents))
    df.columns = [clean_col(c) for c in df.columns]
    return df


def df_to_postgres(df: pd.DataFrame, table: str, conn):
    schema, tname = table.split(".", 1)
    cur = conn.cursor()
    # Drop and recreate
    cur.execute(f'DROP TABLE IF EXISTS {table}')
    cols = df.columns.tolist()
    col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
    cur.execute(f'CREATE TABLE {table} ({col_defs})')
    rows = [tuple(str(v) if v is not None and str(v) != "nan" else None for v in row) for row in df.itertuples(index=False)]
    if rows:
        placeholders = "(" + ",".join(["%s"] * len(cols)) + ")"
        execute_values(cur, f'INSERT INTO {table} VALUES %s', rows)
    conn.commit()
    cur.close()


def get_or_create_file(conn, name: str, display_name: str, description: str, created_by: str) -> int:
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
              description: str, uploader: str, notes: str, activate: bool = True) -> dict:
    df = parse_file(contents, original_filename)
    conn = get_conn()

    file_id = get_or_create_file(conn, name, display_name, description, uploader)
    version = next_version(conn, file_id)
    target_table = f"uploads.{name}_v{version}"

    df_to_postgres(df, target_table, conn)

    # Set all existing to archived, then insert new as active
    cur = conn.cursor()
    cur.execute("UPDATE uploads.file_versions SET status='archived' WHERE file_id=%s", (file_id,))
    cur.execute("""
        INSERT INTO uploads.file_versions
            (file_id, version, original_filename, file_size_bytes, row_count, column_count, target_table, status, uploaded_by, notes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (file_id, version, original_filename, len(contents), len(df), len(df.columns),
          target_table, 'active', uploader, notes))
    version_id = cur.fetchone()[0]
    conn.commit()
    cur.close()

    if activate:
        canonical = f"uploads.{name}"
        df_to_postgres(df, canonical, conn)

    conn.close()
    return {"file_id": file_id, "version_id": version_id, "version": version, "rows": len(df)}


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.id, r.name, r.display_name, r.description, r.created_by,
                   v.version, v.row_count, v.uploaded_at, v.uploaded_by
            FROM uploads.file_registry r
            LEFT JOIN uploads.file_versions v ON v.file_id = r.id AND v.status = 'active'
            ORDER BY r.id
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        files = [
            {"id": r[0], "name": r[1], "display_name": r[2], "description": r[3],
             "created_by": r[4], "version": r[5], "row_count": r[6],
             "uploaded_at": r[7].strftime("%Y-%m-%d %H:%M") if r[7] else "-",
             "uploaded_by": r[8] or "-"}
            for r in rows
        ]
    except Exception as e:
        files = []
        print(f"DB error: {e}")
    return templates.TemplateResponse("index.html", {"request": request, "files": files})


@app.get("/files/{file_id}", response_class=HTMLResponse)
def file_detail(request: Request, file_id: int):
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
               uploaded_at, status, notes, target_table
        FROM uploads.file_versions WHERE file_id=%s ORDER BY version DESC
    """, (file_id,))
    versions = [
        {"id": r[0], "version": r[1], "original_filename": r[2], "row_count": r[3],
         "column_count": r[4], "uploaded_by": r[5],
         "uploaded_at": r[6].strftime("%Y-%m-%d %H:%M") if r[6] else "-",
         "status": r[7], "notes": r[8], "target_table": r[9]}
        for r in cur.fetchall()
    ]

    # Preview: first 20 rows of active version
    preview_cols, preview_rows = [], []
    active_v = next((v for v in versions if v["status"] == "active"), None)
    if active_v:
        try:
            cur.execute(f'SELECT * FROM {active_v["target_table"]} LIMIT 20')
            preview_cols = [desc[0] for desc in cur.description]
            preview_rows = cur.fetchall()
        except Exception as e:
            print(f"Preview error: {e}")

    cur.close(); conn.close()
    return templates.TemplateResponse("file_detail.html", {
        "request": request, "file": file, "versions": versions,
        "preview_cols": preview_cols, "preview_rows": preview_rows
    })


@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    display_name: str = Form(...),
    description: str = Form(""),
    uploader_name: str = Form("anonymous"),
    notes: str = Form(""),
):
    contents = await file.read()
    name = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    try:
        result = do_upload(contents, file.filename, name, display_name, description, uploader_name, notes)
        return RedirectResponse(url=f"/files/{result['file_id']}?success=1", status_code=303)
    except Exception as e:
        return HTMLResponse(f"Upload failed: {e}", status_code=500)


@app.post("/activate/{version_id}")
def activate_version(version_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT file_id, target_table FROM uploads.file_versions WHERE id=%s", (version_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return JSONResponse({"error": "Version not found"}, status_code=404)
    file_id, target_table = row

    # Get canonical name
    cur.execute("SELECT name FROM uploads.file_registry WHERE id=%s", (file_id,))
    name = cur.fetchone()[0]
    canonical = f"uploads.{name}"

    # Copy data
    cur.execute(f"DROP TABLE IF EXISTS {canonical}")
    cur.execute(f"CREATE TABLE {canonical} AS SELECT * FROM {target_table}")

    # Update statuses
    cur.execute("UPDATE uploads.file_versions SET status='archived' WHERE file_id=%s", (file_id,))
    cur.execute("UPDATE uploads.file_versions SET status='active' WHERE id=%s", (version_id,))
    conn.commit()
    cur.close(); conn.close()

    return RedirectResponse(url=f"/files/{file_id}?activated=1", status_code=303)


@app.get("/preview/{version_id}")
def preview(version_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT target_table FROM uploads.file_versions WHERE id=%s", (version_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return JSONResponse({"error": "Not found"}, status_code=404)
    try:
        cur.execute(f"SELECT * FROM {row[0]} LIMIT 50")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        return JSONResponse({"columns": cols, "rows": rows})
    except Exception as e:
        cur.close(); conn.close()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/load-examples")
def load_examples():
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
