"""PPM Data Assistant — Auth, charts, Metabase, inline downloads, sticky input."""
import os, json, csv, uuid, tempfile, threading
import gradio as gr
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI
import plotly.graph_objects as go
import plotly.express as px
import requests as _req

# ── Auth ───────────────────────────────────────────────────────────────────────
PORTAL_USERS = {
    "admin":     {"password": os.getenv("PORTAL_ADMIN_PASS",   ""), "name": "Admin",      "role": "Admin"},
    "developer": {"password": os.getenv("PORTAL_DEV_PASS",     ""), "name": "Developer",  "role": "Developer"},
    "analyst":   {"password": os.getenv("PORTAL_ANALYST_PASS", ""), "name": "Power User", "role": "Analyst"},
    "user":      {"password": os.getenv("PORTAL_USER_PASS",    ""), "name": "End User",   "role": "User"},
}

def auth_check(username: str, password: str) -> bool:
    u = PORTAL_USERS.get(username.lower())
    return bool(u and u["password"] and u["password"] == password)

def user_html(info: dict | None) -> str:
    if not info:
        return ""
    return (f"<div style='display:flex;align-items:center;gap:6px;padding:6px 4px;"
            f"font-size:.8rem;color:#6b7280;border-top:1px solid #e5e7eb;margin-top:auto'>"
            f"<span style='font-size:1rem'>👤</span>"
            f"<b style='color:#374151'>{info['name']}</b>"
            f"<span style='background:#e0e7ff;color:#4338ca;padding:2px 8px;border-radius:10px;"
            f"font-size:.68rem;font-weight:700'>{info['role']}</span></div>")


# ── DB connections ─────────────────────────────────────────────────────────────
def _pg(dbname: str):
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"), port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=dbname, user=os.getenv("POSTGRES_USER", "ppm_user"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )
def get_dwh(): return _pg(os.getenv("POSTGRES_DB", "ppm_datawarehouse"))
def get_app(): return _pg(os.getenv("AGENT_DB", "ppmdatastack"))


# ── Bootstrap ──────────────────────────────────────────────────────────────────
SEED_PROVIDERS = [
    {"name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
     "api_key_env": "GEMINI_API_KEY", "models": [
        {"model_id": "gemini-2.5-flash",      "display_name": "Gemini 2.5 Flash",      "is_free": True,  "is_default": True},
        {"model_id": "gemini-2.0-flash-lite", "display_name": "Gemini 2.0 Flash Lite", "is_free": True,  "is_default": False},
    ]},
    {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY", "models": [
        {"model_id": "gpt-4o-mini", "display_name": "GPT-4o Mini", "is_free": False, "is_default": False},
        {"model_id": "gpt-4o",      "display_name": "GPT-4o",      "is_free": False, "is_default": False},
    ]},
    {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "api_key_env": "DEEPSEEK_API_KEY", "models": [
        {"model_id": "deepseek-chat", "display_name": "DeepSeek Chat", "is_free": False, "is_default": False},
    ]},
    {"name": "HuggingFace", "base_url": "https://api-inference.huggingface.co/v1/", "api_key_env": "HUGGINGFACE_API_KEY", "models": [
        {"model_id": "meta-llama/Llama-3.3-70B-Instruct", "display_name": "Llama 3.3 70B ✦", "is_free": True, "is_default": False},
    ]},
]

def bootstrap():
    conn = get_app(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS llm_providers (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, base_url TEXT NOT NULL,
            api_key_env TEXT, api_key TEXT, is_active BOOLEAN DEFAULT TRUE
        );
        CREATE TABLE IF NOT EXISTS llm_models (
            id SERIAL PRIMARY KEY, provider_id INTEGER REFERENCES llm_providers(id) ON DELETE CASCADE,
            model_id TEXT NOT NULL, display_name TEXT NOT NULL,
            is_free BOOLEAN DEFAULT FALSE, is_default BOOLEAN DEFAULT FALSE, is_active BOOLEAN DEFAULT TRUE
        );
        CREATE TABLE IF NOT EXISTS agent_chat_sessions (
            id SERIAL PRIMARY KEY, title TEXT NOT NULL DEFAULT 'New Chat', created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS agent_chat_messages (
            id SERIAL PRIMARY KEY, session_id INTEGER REFERENCES agent_chat_sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL, content TEXT NOT NULL, sql_used TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    for p in SEED_PROVIDERS:
        cur.execute("INSERT INTO llm_providers (name,base_url,api_key_env) VALUES (%s,%s,%s) ON CONFLICT (name) DO NOTHING RETURNING id",
                    (p["name"], p["base_url"], p["api_key_env"]))
        row = cur.fetchone()
        if row:
            for m in p["models"]:
                cur.execute("INSERT INTO llm_models (provider_id,model_id,display_name,is_free,is_default) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (row[0], m["model_id"], m["display_name"], m["is_free"], m["is_default"]))
    conn.commit(); conn.close()


# ── Providers ─────────────────────────────────────────────────────────────────
def get_active_models():
    conn = get_app(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""SELECT m.id,m.model_id,m.display_name,m.is_free,m.is_default,
                          p.name AS provider_name,p.base_url,p.api_key_env,p.api_key
                   FROM llm_models m JOIN llm_providers p ON p.id=m.provider_id
                   WHERE m.is_active AND p.is_active
                   ORDER BY m.is_default DESC,m.is_free DESC,p.name,m.display_name""")
    rows = cur.fetchall(); conn.close()
    # ponytail: show model name only (no provider prefix) to fit narrow dropdown
    return [(r["display_name"] + (" ✦" if r["is_free"] else ""), dict(r)) for r in rows]

def resolve_key(row): return os.getenv(row.get("api_key_env") or "", "") or row.get("api_key") or ""
def make_client(row): return OpenAI(api_key=resolve_key(row) or "no-key", base_url=row["base_url"]), row["model_id"]


# ── DWH Schema ────────────────────────────────────────────────────────────────
_schema_cache: str | None = None
_schema_lock = threading.Lock()

def get_schema() -> str:
    global _schema_cache
    with _schema_lock:
        if _schema_cache: return _schema_cache
        try:
            conn = get_dwh(); cur = conn.cursor()
            cur.execute("""SELECT table_schema,table_name,column_name FROM information_schema.columns
                           WHERE table_schema IN ('core','mart') ORDER BY table_schema,table_name,ordinal_position""")
            tables: dict[str, list] = {}
            for s, t, c in cur.fetchall():
                tables.setdefault(f"{s}.{t}", []).append(c)
            conn.close()
            _schema_cache = "\n".join(f"  {k}({', '.join(v)})" for k, v in tables.items())
        except Exception as e:
            _schema_cache = "(schema unavailable)"; print(f"Schema: {e}")
        return _schema_cache


# ── Metabase ──────────────────────────────────────────────────────────────────
_mb_token: str | None = None
_MB_BASE = f"http://{os.getenv('METABASE_HOST','metabase')}:{os.getenv('METABASE_PORT','3000')}"

def _mb_get(path: str):
    global _mb_token
    if not _mb_token:
        try:
            r = _req.post(f"{_MB_BASE}/api/session",
                         json={"username": os.getenv("MB_ADMIN_EMAIL",""), "password": os.getenv("MB_ADMIN_PASSWORD","")},
                         timeout=5)
            _mb_token = r.json().get("id")
        except: pass
    if not _mb_token: return None
    try:
        r = _req.get(f"{_MB_BASE}{path}", headers={"X-Metabase-Session": _mb_token}, timeout=10)
        if r.status_code == 401: _mb_token = None; return None
        return r.json()
    except: return None

def mb_list_questions() -> str:
    cards = _mb_get("/api/card?f=all")
    if not cards: return "Could not connect to Metabase."
    lines = ["| ID | Name | Type |", "|----|------|------|"]
    for c in cards[:50]:
        lines.append(f"| {c['id']} | {c['name']} | {c.get('display','?')} |")
    return "\n".join(lines)

def mb_run_question(qid: int) -> tuple[str, list | None]:
    data = _mb_get(f"/api/card/{qid}/query/json")
    if not data or (isinstance(data, dict) and data.get("error")):
        return f"Error running question {qid}.", None
    if not isinstance(data, list) or not data: return "No results.", None
    cols = list(data[0].keys())
    lines = ["| "+" | ".join(cols)+" |", "| "+" | ".join(["---"]*len(cols))+" |"]
    for row in data[:50]:
        lines.append("| "+" | ".join(str(row.get(c,"")) for c in cols)+" |")
    return "\n".join(lines), [cols]+[[row.get(c) for c in cols] for row in data[:100]]

def mb_list_dashboards() -> str:
    data = _mb_get("/api/dashboard")
    if not data: return "Could not connect to Metabase."
    lines = ["| ID | Name |", "|----|------|"]
    for d in (data if isinstance(data, list) else [])[:20]:
        lines.append(f"| {d['id']} | {d['name']} |")
    return "\n".join(lines)


# ── Tools ─────────────────────────────────────────────────────────────────────
TOOLS = [
    {"type":"function","function":{"name":"query_db","description":"Execute a read-only SQL SELECT/WITH query against the PPM PostgreSQL data warehouse.",
     "parameters":{"type":"object","properties":{"sql":{"type":"string"}},"required":["sql"]}}},
    {"type":"function","function":{"name":"list_schemas","description":"List all schemas, tables and columns. Call when unsure about table/column names.",
     "parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"list_dbt_models","description":"List dbt model files by layer.",
     "parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"list_metabase_questions","description":"List saved Metabase questions/cards.",
     "parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"run_metabase_question","description":"Run a saved Metabase question by ID.",
     "parameters":{"type":"object","properties":{"question_id":{"type":"integer"}},"required":["question_id"]}}},
    {"type":"function","function":{"name":"list_metabase_dashboards","description":"List available Metabase dashboards.",
     "parameters":{"type":"object","properties":{}}}},
]

def _do_select(sql: str):
    conn = get_dwh(); cur = conn.cursor()
    if not sql.strip().upper().lstrip("(").startswith(("SELECT", "WITH")):
        conn.close(); return "Only SELECT/WITH queries allowed.", None, None
    cur.execute(sql)
    cols = [d[0] for d in cur.description]; rows = cur.fetchmany(100); conn.close()
    return cols, rows, sql

def _rows_to_md(cols, rows) -> str:
    lines = ["| "+" | ".join(str(c) for c in cols)+" |", "| "+"| ".join(["---"]*len(cols))+" |"]
    lines += ["| "+" | ".join("" if v is None else str(v) for v in r)+" |" for r in rows]
    return "\n".join(lines)

def dispatch(name: str, args: dict) -> tuple[str, str | None, list | None]:
    if name == "query_db":
        sql = args["sql"]
        try:
            cols, rows, sql = _do_select(sql)
            if isinstance(cols, str): return cols, sql, None
            if not rows: return "No results found.", sql, None
            return _rows_to_md(cols, rows), sql, [list(cols)] + [list(r) for r in rows]
        except Exception as e: return f"**Query Error:** {e}", sql, None

    if name == "list_schemas":
        try:
            cols, rows, sql = _do_select("""
                SELECT c.table_schema,c.table_name,
                       string_agg(c.column_name||' ('||c.data_type||')',', ' ORDER BY c.ordinal_position) AS columns
                FROM information_schema.columns c
                WHERE c.table_schema IN ('core','mart','staging')
                GROUP BY c.table_schema,c.table_name ORDER BY c.table_schema,c.table_name""")
            if isinstance(cols, str): return cols, None, None
            return _rows_to_md(cols, rows), None, None
        except Exception as e: return f"Error: {e}", None, None

    if name == "list_dbt_models":
        root = "/dbt/models"
        if not os.path.exists(root): return "dbt models directory not found.", None, None
        files = [os.path.relpath(os.path.join(d, f), root)
                 for d, _, fs in os.walk(root) for f in fs if f.endswith(".sql")]
        return "\n".join(sorted(files)), None, None

    if name == "list_metabase_questions": return mb_list_questions(), None, None
    if name == "run_metabase_question":
        t, raw = mb_run_question(args["question_id"]); return t, None, raw
    if name == "list_metabase_dashboards": return mb_list_dashboards(), None, None
    return f"Unknown tool: {name}", None, None


# ── Chart ─────────────────────────────────────────────────────────────────────
def _num(v) -> bool:
    try: float(v); return True
    except: return False

import re, base64

def _parse_md_table(text: str) -> list | None:
    """Extract first markdown table from LLM text as [[cols], [row], ...] fallback."""
    pattern = r'\|(.+)\|\n\|[-:\s|]+\|\n((?:\|.+\|\n?)+)'
    m = re.search(pattern, text)
    if not m: return None
    header = [h.strip() for h in m.group(1).split('|') if h.strip()]
    rows = []
    for line in m.group(2).strip().split('\n'):
        if '|' not in line: continue
        vals = [v.strip() for v in line.split('|') if v.strip()]
        if vals and len(vals) == len(header): rows.append(vals)
    return [header] + rows if len(rows) >= 2 else None

def _build_fig(raw: list) -> "go.Figure | None":
    if not raw or len(raw) < 3: return None
    cols = raw[0]; rows = raw[1:]
    if not rows or len(cols) < 2: return None
    cat = [i for i, c in enumerate(cols) if not all(_num(r[i]) for r in rows if r[i] is not None)]
    num = [i for i in range(len(cols)) if i not in cat
           and all(_num(r[i]) for r in rows if r[i] is not None)]
    if not num: return None
    date_kw = ("date","week","month","year","day","period","created","updated","started","at")
    date_col = next((i for i, c in enumerate(cols) if any(k in str(c).lower() for k in date_kw)), None)
    xi = date_col if date_col is not None else (cat[0] if cat else 0)
    xs = [str(r[xi]) for r in rows]
    y0 = num[0]; ys = [float(r[y0]) if _num(r[y0]) else 0 for r in rows]
    yl = str(cols[y0]); xl = str(cols[xi])

    PALETTE = ["#6366f1","#8b5cf6","#06b6d4","#10b981","#f59e0b","#ef4444","#ec4899","#3b82f6"]

    if date_col is not None:
        fig = go.Figure(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            line=dict(color=PALETTE[0], width=3),
            marker=dict(size=6, color=PALETTE[0]),
            fill="tozeroy", fillcolor="rgba(99,102,241,0.08)", name=yl,
        ))
        fig.update_layout(title=dict(text=f"{yl} over time", font_size=14))
    elif len(rows) <= 8 and len(num) == 1:
        fig = go.Figure(go.Pie(
            labels=xs, values=ys, hole=0.4,
            marker=dict(colors=PALETTE, line=dict(color="#fff", width=2)),
        ))
        fig.update_layout(title=dict(text=yl, font_size=14))
    else:
        if len(num) > 1:
            fig = go.Figure()
            for idx, ni in enumerate(num):
                fig.add_trace(go.Bar(
                    name=str(cols[ni]), x=xs,
                    y=[float(r[ni]) if _num(r[ni]) else 0 for r in rows],
                    marker_color=PALETTE[idx % len(PALETTE)],
                ))
            fig.update_layout(barmode="group", title=dict(text=str(cols[num[0]]), font_size=14))
        else:
            colors = PALETTE[:len(rows)] if len(rows) <= len(PALETTE) else PALETTE[0]
            fig = go.Figure(go.Bar(
                x=xs, y=ys, marker_color=colors,
                marker_line=dict(color="rgba(255,255,255,.3)", width=1), name=yl,
            ))
            fig.update_layout(title=dict(text=f"{yl} by {xl}", font_size=14))

    fig.update_layout(
        height=340, margin=dict(l=40, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11, color="#374151"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25),
        xaxis=dict(gridcolor="rgba(0,0,0,.06)", linecolor="rgba(0,0,0,.1)"),
        yaxis=dict(gridcolor="rgba(0,0,0,.06)", linecolor="rgba(0,0,0,.1)"),
    )
    return fig

def make_chart_html(raw: list | None, answer_text: str = "") -> str:
    """Generate chart HTML for embedding in chatbot message or separate gr.HTML."""
    # Try raw_data first, fallback to parsing markdown table from answer
    data = raw
    if not data and answer_text:
        data = _parse_md_table(answer_text)
    fig = _build_fig(data) if data else None
    if not fig: return ""
    # ponytail: use CDN in gr.HTML (not chatbot), safe for non-sandboxed components
    return fig.to_html(include_plotlyjs="cdn", full_html=False,
                       config={"responsive": True, "displayModeBar": False})


# ── Inline downloads ──────────────────────────────────────────────────────────
DL_DIR = "/tmp/ppm_agent_dl"
os.makedirs(DL_DIR, exist_ok=True)

def _save_dl(raw: list, suffix: str, writer_fn) -> str:
    fid = uuid.uuid4().hex[:10]
    path = f"{DL_DIR}/{fid}{suffix}"
    writer_fn(path, raw); return path

def _write_csv(path, raw):
    cols, rows = raw[0], raw[1:]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(cols); w.writerows(rows)

def _write_md(path, raw):
    cols, rows = raw[0], raw[1:]
    lines = ["| "+" | ".join(str(c) for c in cols)+" |",
             "| "+"| ".join(["---"]*len(cols))+" |"]
    lines += ["| "+" | ".join(str(v) for v in r)+" |" for r in rows]
    open(path, "w", encoding="utf-8").write("\n".join(lines))

def _write_excel(path, raw):
    try:
        import openpyxl; wb = openpyxl.Workbook(); ws = wb.active
        ws.append(raw[0])
        for r in raw[1:]: ws.append([str(v) if v is not None else "" for v in r])
        wb.save(path)
    except ImportError: _write_csv(path.replace(".xlsx",".csv"), raw)

def make_dl_html(raw: list | None) -> str:
    if not raw or len(raw) < 2: return ""
    try:
        csv_p   = _save_dl(raw, ".csv",  _write_csv)
        md_p    = _save_dl(raw, ".md",   _write_md)
        excel_p = _save_dl(raw, ".xlsx", _write_excel)
    except Exception as e:
        return f"<span style='font-size:.75rem;color:#9ca3af'>Download error: {e}</span>"
    s = "font-size:.75rem;color:#6b7280;text-decoration:none;padding:2px 6px;border:1px solid #e5e7eb;border-radius:4px;margin-right:4px"
    return (f"<div style='margin-top:10px;display:flex;align-items:center;gap:4px'>"
            f"<span style='font-size:.72rem;color:#9ca3af'>📥 Download:</span>"
            f"<a href='/gradio_api/file={csv_p}'   download style='{s}'>CSV</a>"
            f"<a href='/gradio_api/file={excel_p}' download style='{s}'>Excel</a>"
            f"<a href='/gradio_api/file={md_p}'    download style='{s}'>Markdown</a>"
            f"</div>")


# ── Insights ──────────────────────────────────────────────────────────────────
def split_insights(text: str) -> tuple[str, str]:
    """Returns (main_text, insights_html_for_inline_embedding)."""
    idx = text.find("## 💡")
    if idx == -1: return text, ""
    main = text[:idx].strip()
    ins_lines = text[idx:].split("\n")
    items = "".join(
        f"<li style='margin-bottom:4px'>{l.lstrip('-•* ').strip()}</li>"
        for l in ins_lines[1:] if l.strip().lstrip("-•* ").strip()
    )
    html = (
        "<div style='background:linear-gradient(135deg,#eef2ff,#f0fdf4);"
        "border-left:4px solid #6366f1;border-radius:8px;padding:12px 16px;margin-top:14px;"
        "box-shadow:0 1px 4px rgba(99,102,241,.08)'>"
        "<b style='color:#4338ca;font-size:.84rem;letter-spacing:.01em'>💡 Key Insights</b>"
        f"<ul style='margin:8px 0 0;padding-left:18px;font-size:.84rem;line-height:1.75;color:#1e1b4b'>{items}</ul>"
        "</div>"
    )
    return main, html


# ── Chat history ──────────────────────────────────────────────────────────────
def create_session():
    try:
        conn = get_app(); cur = conn.cursor()
        cur.execute("INSERT INTO agent_chat_sessions DEFAULT VALUES RETURNING id")
        sid = cur.fetchone()[0]; conn.commit(); conn.close(); return sid
    except Exception as e: print(f"create_session: {e}"); return None

def save_msg(sid, role, content, sql=None):
    if not sid: return
    try:
        conn = get_app(); cur = conn.cursor()
        cur.execute("INSERT INTO agent_chat_messages (session_id,role,content,sql_used) VALUES (%s,%s,%s,%s)",
                    (sid, role, content, sql))
        if role == "user":
            cur.execute("UPDATE agent_chat_sessions SET title=%s WHERE id=%s AND title='New Chat'",
                        (content[:60], sid))
        conn.commit(); conn.close()
    except Exception as e: print(f"save_msg: {e}")

def load_sessions():
    try:
        conn = get_app(); cur = conn.cursor()
        cur.execute("""SELECT s.id,s.title,COUNT(m.id) FROM agent_chat_sessions s
                       LEFT JOIN agent_chat_messages m ON m.session_id=s.id
                       GROUP BY s.id,s.title,s.created_at ORDER BY s.created_at DESC LIMIT 30""")
        rows = cur.fetchall(); conn.close()
        return [((t[:36]+"…" if len(t)>36 else t)+f" ({c})", str(sid)) for sid,t,c in rows]
    except Exception as e: print(f"load_sessions: {e}"); return []

def load_history(sid):
    if not sid: return []
    try:
        conn = get_app(); cur = conn.cursor()
        cur.execute("SELECT role,content FROM agent_chat_messages WHERE session_id=%s ORDER BY created_at", (int(sid),))
        rows = cur.fetchall(); conn.close()
        return [{"role": r, "content": c} for r, c in rows]
    except Exception as e: print(f"load_history: {e}"); return []


# ── Chat engine ────────────────────────────────────────────────────────────────
SYSTEM = """You are PPM Data Assistant — an expert analyst for Project & Portfolio Management data.

DATA WAREHOUSE TABLES:
{schema}

RULES:
- Use mart.* first, core.* for joins, avoid staging.* unless asked
- time_spent_seconds / 3600.0 = hours
- Use LIMIT 100 for exploration, no LIMIT for aggregations
- Call list_schemas if unsure about column names
- If Metabase has a relevant question, prefer run_metabase_question
- Respond in the same language the user writes in

VISUALIZATION RULE (CRITICAL):
When the user asks to "show as chart/graph", "visualize", "plot", "grafik olarak göster", "grafik çiz" etc.:
  1. ALWAYS call query_db with appropriate SQL to get the data
  2. Return the data as a brief markdown table
  3. The system renders the chart automatically — do NOT describe chart types or axes in text
  4. Just write 1-2 sentences about what the data shows

INSIGHTS RULE (MANDATORY):
After EVERY response that contains data from query_db or run_metabase_question, you MUST end with:
## 💡 Key Insights
- [specific finding 1 with numbers]
- [specific finding 2 with numbers]
- [actionable observation or comparison]"""

def run_chat(message, history, session_id, model_row):
    if not model_row:
        return "⚠️ No model selected. Choose a model from the dropdown.", session_id, None, []
    key = resolve_key(model_row)
    if not key:
        return (f"⚠️ No API key for **{model_row['provider_name']}**. "
                f"Set `{model_row['api_key_env']}` in `.env` and restart.", session_id, None, [])
    if not session_id: session_id = create_session()
    save_msg(session_id, "user", message)

    system = SYSTEM.format(schema=get_schema())
    msgs = [{"role":"system","content":system}]
    for h in history:
        if isinstance(h, dict): msgs.append({"role":h["role"],"content":h["content"]})
    msgs.append({"role":"user","content":message})

    client, model_id = make_client(model_row)
    all_sqls: list[str] = []; last_raw = None

    for _ in range(12):
        try:
            resp = client.chat.completions.create(model=model_id, messages=msgs, tools=TOOLS)
        except Exception as e:
            err = str(e)
            if any(x in err for x in ("402","insufficient","quota","429")):
                return f"⚠️ **Quota/Balance error ({model_row['provider_name']}).** Top up credits.\n`{err[:200]}`", session_id, None, []
            return f"❌ **API Error ({model_row['provider_name']}):** {err[:300]}", session_id, None, []

        msg = resp.choices[0].message
        if not msg.tool_calls:
            answer = msg.content or ""
            sql_html = ""
            if all_sqls:
                def _esc(s): return s.strip().replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                if len(all_sqls) == 1:
                    blocks = f"<pre style='background:#1a1b2e;color:#a9b1d6;padding:10px 14px;border-radius:6px;font-size:.76rem;margin:6px 0 0;overflow-x:auto;white-space:pre-wrap'>{_esc(all_sqls[0])}</pre>"
                else:
                    blocks = "".join(
                        f"<div style='margin-top:6px'>"
                        f"<span style='font-size:.68rem;color:#6b7280;font-weight:600;text-transform:uppercase;letter-spacing:.06em'>Query {i}</span>"
                        f"<pre style='background:#1a1b2e;color:#a9b1d6;padding:10px 14px;border-radius:6px;font-size:.76rem;margin:3px 0 0;overflow-x:auto;white-space:pre-wrap'>{_esc(s)}</pre></div>"
                        for i, s in enumerate(all_sqls, 1)
                    )
                count = f" ({len(all_sqls)} queries)" if len(all_sqls) > 1 else ""
                sql_html = (f"\n\n<details style='margin-top:8px'>"
                            f"<summary style='cursor:pointer;color:#9ca3af;font-size:.76rem;user-select:none'>"
                            f"🔍 Generated SQL{count}</summary>{blocks}</details>")
            full_answer = answer + sql_html
            save_msg(session_id, "assistant", full_answer, "\n---\n".join(all_sqls) or None)
            return full_answer, session_id, last_raw, all_sqls

        msgs.append({"role":"assistant","content":msg.content,
                     "tool_calls":[{"id":tc.id,"type":"function",
                                    "function":{"name":tc.function.name,"arguments":tc.function.arguments}}
                                   for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            result, sql, raw = dispatch(tc.function.name, json.loads(tc.function.arguments))
            if sql: all_sqls.append(sql)
            if raw: last_raw = raw
            msgs.append({"role":"tool","tool_call_id":tc.id,"content":result})

    return "Maximum iterations reached.", session_id, last_raw, all_sqls


# ── Admin helpers ─────────────────────────────────────────────────────────────
def admin_providers():
    conn = get_app(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id,name,base_url,api_key_env,is_active FROM llm_providers ORDER BY name")
    rows = cur.fetchall(); conn.close()
    return [[r["id"],r["name"],r["base_url"],r["api_key_env"] or "",r["is_active"]] for r in rows]

def admin_models():
    conn = get_app(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""SELECT m.id,p.name,m.model_id,m.display_name,m.is_free,m.is_default,m.is_active
                   FROM llm_models m JOIN llm_providers p ON p.id=m.provider_id ORDER BY p.name,m.display_name""")
    rows = cur.fetchall(); conn.close()
    return [[r["id"],r["name"],r["model_id"],r["display_name"],r["is_free"],r["is_default"],r["is_active"]] for r in rows]

def admin_upsert_prov(name, url, env, key):
    if not name or not url: return "❌ Name and Base URL required."
    try:
        conn = get_app(); cur = conn.cursor()
        cur.execute("INSERT INTO llm_providers (name,base_url,api_key_env,api_key) VALUES (%s,%s,%s,%s) ON CONFLICT (name) DO UPDATE SET base_url=EXCLUDED.base_url,api_key_env=EXCLUDED.api_key_env,api_key=EXCLUDED.api_key",
                    (name.strip(),url.strip(),env.strip() or None,key.strip() or None))
        conn.commit(); conn.close(); return f"✅ Provider '{name}' saved."
    except Exception as e: return f"❌ {e}"

def admin_add_model(prov, mid, disp, free, default):
    if not all([prov,mid,disp]): return "❌ Provider, Model ID and Display Name required."
    try:
        conn = get_app(); cur = conn.cursor()
        cur.execute("SELECT id FROM llm_providers WHERE name=%s", (prov,))
        row = cur.fetchone()
        if not row: return f"❌ Provider '{prov}' not found."
        if default: cur.execute("UPDATE llm_models SET is_default=FALSE WHERE provider_id=%s",(row[0],))
        cur.execute("INSERT INTO llm_models (provider_id,model_id,display_name,is_free,is_default) VALUES (%s,%s,%s,%s,%s)",
                    (row[0],mid.strip(),disp.strip(),bool(free),bool(default)))
        conn.commit(); conn.close(); return f"✅ Model '{disp}' added."
    except Exception as e: return f"❌ {e}"

def admin_test(name):
    try:
        conn = get_app(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT m.model_id,p.base_url,p.api_key_env,p.api_key FROM llm_models m
                       JOIN llm_providers p ON p.id=m.provider_id
                       WHERE p.name=%s AND m.is_active ORDER BY m.is_default DESC LIMIT 1""", (name,))
        row = cur.fetchone(); conn.close()
        if not row: return f"❌ No active models for '{name}'."
        key = os.getenv(row["api_key_env"] or "","") or row.get("api_key") or ""
        if not key: return f"❌ No API key. Set env: {row['api_key_env']}"
        c = OpenAI(api_key=key, base_url=row["base_url"])
        r = c.chat.completions.create(model=row["model_id"], messages=[{"role":"user","content":"Reply with OK"}], max_tokens=5)
        return f"✅ **{name}** `{row['model_id']}` → `{r.choices[0].message.content or '(tool call)'}`"
    except Exception as e: return f"❌ {e}"


# ── Startup ────────────────────────────────────────────────────────────────────
try:   bootstrap();  print("✅ DB bootstrap OK")
except Exception as e: print(f"⚠️  Bootstrap: {e}")
try:   get_schema(); print("✅ DWH schema loaded")
except Exception as e: print(f"⚠️  Schema: {e}")

MODEL_ROWS    = get_active_models()
MODEL_CHOICES = [(label, json.dumps(row)) for label, row in MODEL_ROWS]
DEFAULT_MODEL = next((j for _, j in MODEL_CHOICES if json.loads(j).get("is_default")),
                     MODEL_CHOICES[0][1] if MODEL_CHOICES else None)


# ── CSS ────────────────────────────────────────────────────────────────────────
CSS = """
/* ── Full-width zero-gap layout ────────────────────────────── */
html,body{height:100%;margin:0;padding:0}
/* Override Gradio's max-width at all breakpoints */
.gradio-container,.fillable,.main.fillable,.contain{
  max-width:100%!important;width:100%!important;
  padding:0!important;margin:0!important
}
.wrap{padding:0!important;margin:0!important}
footer,.svelte-1cl284s{display:none!important}
/* Chat view: overflow hidden (flex fills viewport) */
.chat-page{overflow:hidden!important}
/* Settings view: scrollable with proper padding */
.settings-page{
  height:100vh!important;overflow-y:auto!important;
  padding:20px 28px 40px!important;
  box-sizing:border-box!important
}

/* Main row */
.main-row{
  height:100vh!important;overflow:hidden!important;
  gap:0!important;padding:0!important;margin:0!important
}

/* ── Left panel ─────────────────────────────────────────────── */
.left-col{
  display:flex!important;flex-direction:column!important;
  height:100vh!important;overflow:hidden!important;
  padding:8px 6px 6px!important;gap:4px!important;
  /* no border */
}
.sess-scroll{flex:1!important;overflow-y:auto!important;min-height:0!important}

/* ── Right panel ────────────────────────────────────────────── */
.right-col{
  display:flex!important;flex-direction:column!important;
  height:100vh!important;overflow:hidden!important;padding:0!important
}
#ppm-chatbot{flex:1!important;overflow-y:auto!important;min-height:0!important;height:auto!important;max-height:none!important}
#ppm-chatbot>div{height:100%!important;overflow-y:auto!important}

.input-bar{
  flex-shrink:0!important;
  padding:6px 6px 4px!important;
  background:var(--background-fill-primary)!important;gap:6px!important
}

/* ── Session list (no radio circles, no label) ──────────────── */
.sess-list .wrap{border:none!important;padding:0!important;gap:1px!important;background:transparent!important}
.sess-list label{border:none!important;border-radius:6px!important;padding:5px 8px!important;
  cursor:pointer!important;font-size:.79rem!important;line-height:1.35!important;display:block!important}
.sess-list label:hover{background:rgba(99,102,241,.1)!important}
.sess-list label.selected{background:rgba(99,102,241,.15)!important;font-weight:600!important}
.sess-list input[type=radio]{display:none!important}
.sess-list>div>div>span,.sess-list .block>label:not([class*=svelte]){display:none!important}
.sess-list .block{border:none!important;padding:0!important;background:transparent!important}

/* ── Section labels — purple like model label ───────────────── */
.sec-label{
  font-size:.68rem!important;font-weight:800!important;color:#6366f1!important;
  text-transform:uppercase!important;letter-spacing:.09em!important;
  padding:8px 2px 2px!important;margin:0!important
}

/* ── Model dropdown: smaller font ──────────────────────────── */
.left-col select,.left-col .svelte-select,.left-col [data-testid="dropdown"] span,
.left-col .dropdown-arrow~div{font-size:.77rem!important}

/* Remove all dividing borders */
.left-col,.right-col,.input-bar,.sess-scroll{border:none!important;box-shadow:none!important}
.gradio-container *{border-color:transparent!important}
/* Keep only chatbot message borders */
#ppm-chatbot .message{border:1px solid var(--border-color-primary)!important}

.settings-header{font-size:1.1rem;font-weight:700;margin-bottom:8px}
"""

PLACEHOLDER = """<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
height:100%;color:#9ca3af;text-align:center;padding:24px 32px">
<div style="font-size:2.4rem;margin-bottom:10px">🗂️</div>
<div style="font-size:1.05rem;font-weight:600;color:#6b7280;margin-bottom:4px">PPM Data Assistant</div>
<div style="font-size:.8rem;color:#9ca3af;margin-bottom:22px">Ask anything about your project data in any language</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:440px;width:100%">
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:.78rem;color:#374151;text-align:left;cursor:default">📊 Open issues per project?</div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:.78rem;color:#374151;text-align:left;cursor:default">⏱️ Top users by logged hours?</div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:.78rem;color:#374151;text-align:left;cursor:default">🚨 Projects with overdue tasks?</div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:.78rem;color:#374151;text-align:left;cursor:default">📋 All epics and their status?</div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:.78rem;color:#374151;text-align:left;cursor:default">🏛️ List Metabase reports on budgets</div>
  <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:10px 12px;font-size:.78rem;color:#374151;text-align:left;cursor:default">📈 Effort trend month by month</div>
</div>
<div style="margin-top:18px;font-size:.72rem;color:#d1d5db">Tools: SQL · Metabase · dbt models · Charts · Downloads</div>
<div style="margin-top:14px;display:flex;gap:16px;align-items:center">
  <a href="/gradio_api/file=/app/docs/guide_en.html" target="_blank"
     style="font-size:.78rem;color:#6366f1;text-decoration:none;padding:5px 12px;
            border:1px solid #c7d2fe;border-radius:20px;background:#eef2ff">
    📖 Usage Guide (EN)
  </a>
  <a href="/gradio_api/file=/app/docs/guide_tr.html" target="_blank"
     style="font-size:.78rem;color:#6366f1;text-decoration:none;padding:5px 12px;
            border:1px solid #c7d2fe;border-radius:20px;background:#eef2ff">
    📖 Kullanım Kılavuzu (TR)
  </a>
</div>
</div>"""

LOGIN_HTML = """<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:70vh">
  <div style="background:white;border:1px solid #e5e7eb;border-radius:16px;padding:40px 48px;width:360px;box-shadow:0 4px 24px rgba(0,0,0,.08)">
    <div style="text-align:center;margin-bottom:24px">
      <div style="font-size:2rem;margin-bottom:8px">🗂️</div>
      <div style="font-size:1.2rem;font-weight:700;color:#111827">PPM Data Assistant</div>
      <div style="font-size:.83rem;color:#6b7280;margin-top:4px">Sign in with your PPM credentials</div>
    </div>
  </div>
</div>"""


# ── Build UI ──────────────────────────────────────────────────────────────────
with gr.Blocks(title="PPM Data Assistant", fill_width=True) as demo:
    auth_state       = gr.State(None)
    session_state    = gr.State(None)
    model_row_state  = gr.State(json.loads(DEFAULT_MODEL) if DEFAULT_MODEL else None)

    # ════════════════════════════════════════════════════════════════════════════
    # LOGIN VIEW
    # ════════════════════════════════════════════════════════════════════════════
    with gr.Column(visible=True) as login_view:
        gr.HTML("""<div style="display:flex;flex-direction:column;align-items:center;
                   justify-content:center;min-height:70vh">
          <div style="background:white;border:1px solid #e5e7eb;border-radius:16px;
                      padding:40px 48px;width:360px;box-shadow:0 4px 24px rgba(0,0,0,.08)">
            <div style="text-align:center;margin-bottom:24px">
              <div style="font-size:2rem;margin-bottom:8px">🗂️</div>
              <div style="font-size:1.2rem;font-weight:700;color:#111827">PPM Data Assistant</div>
              <div style="font-size:.83rem;color:#6b7280;margin-top:4px">Sign in with your PPM credentials</div>
            </div>""")
        login_user = gr.Textbox(label="Username", placeholder="admin", max_lines=1)
        login_pass = gr.Textbox(label="Password", type="password", max_lines=1)
        login_btn  = gr.Button("Sign in", variant="primary")
        login_err  = gr.HTML("")
        gr.HTML("</div></div>")

    # ════════════════════════════════════════════════════════════════════════════
    # MAIN CHAT VIEW
    # ════════════════════════════════════════════════════════════════════════════
    with gr.Column(visible=False) as app_view:

        # ── Chat layout ────────────────────────────────────────────────────────
        with gr.Column(visible=True, elem_classes=["chat-page"]) as chat_view:
            with gr.Row(elem_classes=["main-row"]):

                # Left panel
                with gr.Column(scale=1, min_width=200, elem_classes=["left-col"]):
                    model_dd = gr.Dropdown(label="Model  (✦ free)",
                                           choices=MODEL_CHOICES, value=DEFAULT_MODEL)
                    new_btn     = gr.Button("＋ New Chat", variant="primary", size="sm")
                    refresh_btn = gr.Button("↻  Refresh", size="sm", variant="secondary")

                    with gr.Column(elem_classes=["sess-scroll"]):
                        gr.HTML("<p class='sec-label'>Conversation History</p>")
                        sessions_radio = gr.Radio(
                            label=None, show_label=False, choices=[],
                            interactive=True, elem_classes=["sess-list"],
                            container=False,
                        )

                    # Guide links + bottom controls
                    gr.HTML(
                        "<div style='border-top:1px solid #e5e7eb;padding-top:8px;margin-top:4px'>"
                        "<a href='/gradio_api/file=/app/docs/guide_en.html' target='_blank' "
                        "style='display:block;font-size:.78rem;color:#6366f1;text-decoration:none;"
                        "padding:4px 2px;border-radius:4px' "
                        "onmouseover=\"this.style.background='rgba(99,102,241,.08)'\" "
                        "onmouseout=\"this.style.background=''\">📖 Usage Guide (EN)</a>"
                        "<a href='/gradio_api/file=/app/docs/guide_tr.html' target='_blank' "
                        "style='display:block;font-size:.78rem;color:#6366f1;text-decoration:none;"
                        "padding:4px 2px;border-radius:4px' "
                        "onmouseover=\"this.style.background='rgba(99,102,241,.08)'\" "
                        "onmouseout=\"this.style.background=''\">📖 Kullanım Kılavuzu (TR)</a>"
                        "</div>"
                    )
                    user_display = gr.HTML("")
                    with gr.Row():
                        logout_btn  = gr.Button("Logout", size="sm", variant="secondary", scale=1)
                        settings_btn= gr.Button("⚙ Settings", size="sm", variant="secondary", scale=1)

                # Right panel
                with gr.Column(scale=4, elem_classes=["right-col"]):
                    placeholder  = gr.HTML(PLACEHOLDER, visible=True)
                    chatbot = gr.Chatbot(
                        height=None, render_markdown=True, visible=False,
                        autoscroll=True, show_label=False, elem_id="ppm-chatbot",
                        buttons=["copy"], sanitize_html=False,
                    )
                    chart_html = gr.HTML("", visible=False)

                    with gr.Row(elem_classes=["input-bar"]):
                        msg_box = gr.Textbox(
                            placeholder="Ask about your PPM data… (Enter to send, Shift+Enter for new line)",
                            show_label=False, lines=3, max_lines=6, scale=8,
                        )
                        send_btn = gr.Button("Send ▶", variant="primary", scale=1, min_width=80)

        # ── Settings view ──────────────────────────────────────────────────────
        with gr.Column(visible=False, elem_classes=["settings-page"]) as settings_view:
            with gr.Row():
                gr.Markdown("## ⚙ Settings — Providers & Models")
                back_btn = gr.Button("← Back to Chat", variant="secondary", scale=0, min_width=130)
            settings_msg = gr.Markdown("")

            gr.Markdown("### LLM Providers")
            providers_df = gr.Dataframe(
                headers=["ID", "Name", "Base URL", "API Key Env", "Active"],
                value=admin_providers(), interactive=False,
                wrap=True,
            )
            with gr.Row():
                s_pn = gr.Textbox(label="Name", placeholder="My Provider", scale=1)
                s_pu = gr.Textbox(label="Base URL", placeholder="https://api.example.com/v1", scale=2)
                s_pe = gr.Textbox(label="API Key Env Var", placeholder="MY_API_KEY", scale=1)
                s_pk = gr.Textbox(label="Direct API Key", type="password", placeholder="sk-…", scale=1)
            with gr.Row():
                save_prov = gr.Button("Save Provider", variant="primary", scale=0, min_width=140)
                test_name = gr.Textbox(label="Test Provider Name", placeholder="Google Gemini", scale=2)
                test_prov = gr.Button("🔌 Test Connection", scale=0, min_width=140)
            ref_admin  = gr.Button("↻ Refresh Tables", size="sm")

            gr.Markdown("---\n### Models")
            models_df = gr.Dataframe(
                headers=["ID", "Provider", "Model ID", "Display Name", "Free", "Default", "Active"],
                value=admin_models(), interactive=False,
                wrap=True,
            )
            with gr.Row():
                s_mp  = gr.Textbox(label="Provider Name",  placeholder="Google Gemini", scale=1)
                s_mi  = gr.Textbox(label="Model ID",       placeholder="gemini-2.5-flash", scale=1)
                s_md  = gr.Textbox(label="Display Name",   placeholder="Gemini 2.5 Flash", scale=1)
                s_mf  = gr.Checkbox(label="Free Tier", scale=0)
                s_md2 = gr.Checkbox(label="Set as Default", scale=0)
            add_model = gr.Button("Add Model", variant="primary", scale=0, min_width=120)


    # ════════════════════════════════════════════════════════════════════════════
    # HANDLERS
    # ════════════════════════════════════════════════════════════════════════════

    def _show_app(info: dict):
        """Helper: transition to app view with user info."""
        return (gr.update(visible=False),   # login_view
                gr.update(visible=True),    # app_view
                info,                        # auth_state
                user_html(info),             # user_display
                gr.update(choices=load_sessions(), value=None))  # sessions_radio

    def on_load(request: gr.Request):
        """Auto-login if ppm_user URL param present (embedded via portal)."""
        ppm_user = request.query_params.get("ppm_user", "").lower()
        if ppm_user and ppm_user in PORTAL_USERS:
            info = PORTAL_USERS[ppm_user].copy(); info["username"] = ppm_user
            lv, av, auth, udisp, sess = _show_app(info)
            return lv, av, auth, udisp, sess
        # Not embedded — show login
        return gr.update(visible=True), gr.update(visible=False), None, "", gr.update(choices=[], value=None)

    def do_login(username, password):
        if not username or not password:
            return gr.update(), gr.update(), None, "", gr.update(), "<span style='color:red;font-size:.85rem'>Please enter username and password.</span>"
        if not auth_check(username, password):
            return gr.update(), gr.update(), None, "", gr.update(), "<span style='color:red;font-size:.85rem'>❌ Invalid credentials. Try again.</span>"
        info = PORTAL_USERS[username.lower()].copy(); info["username"] = username.lower()
        lv, av, auth, udisp, sess = _show_app(info)
        return lv, av, auth, udisp, sess, ""

    def do_logout():
        return (gr.update(visible=True),   # login_view
                gr.update(visible=False),  # app_view
                None,                       # auth_state
                "",                         # user_display
                "",                         # login_user clear
                "")                         # login_pass clear

    def on_model_change(j): return json.loads(j) if j else None
    def refresh_sessions(): return gr.update(choices=load_sessions(), value=None)

    def on_new_chat():
        return (None, gr.update(value=None), "",
                gr.update(visible=True), gr.update(visible=False, value=[]),
                gr.update(visible=False, value=""))

    def on_select_session(sid_str, cur_sid):
        """Load and display stored history — never re-runs LLM."""
        blank = (cur_sid, gr.update(visible=True), gr.update(visible=False, value=[]),
                 gr.update(visible=False, value=""))
        if not sid_str: return blank
        try: sid = int(sid_str)
        except: return blank
        msgs = load_history(sid)
        if msgs:
            return sid, gr.update(visible=False), gr.update(visible=True, value=msgs), gr.update(visible=False, value="")
        return (sid,) + blank[1:]

    def on_send(message, history, sid, model_row):
        history = list(history or [])
        if not message.strip():
            show = bool(history)
            return sid, "", gr.update(visible=not show), gr.update(visible=show), gr.update(visible=False, value="")

        answer, new_sid, raw, _ = run_chat(message, history, sid, model_row)

        # Split insights out of main text
        main_text, ins_html = split_insights(answer)

        # Chart: from raw_data or parsed from LLM response text
        chart_h = make_chart_html(raw, main_text)

        # Download links
        dl_html = make_dl_html(raw)

        # Compose full display: main text + insights inline + downloads
        display = main_text
        if ins_html:
            display += "\n\n" + ins_html
        if dl_html:
            display += "\n\n" + dl_html

        new_hist = history + [
            {"role": "user",      "content": message},
            {"role": "assistant", "content": display},
        ]
        return (
            new_sid, "",
            gr.update(visible=False),
            gr.update(visible=True, value=new_hist),
            gr.update(visible=bool(chart_h), value=chart_h),
        )

    def show_settings():
        return gr.update(visible=False), gr.update(visible=True), admin_providers(), admin_models()

    def hide_settings():
        rows = get_active_models()
        ch   = [(l, json.dumps(r)) for l, r in rows]
        defv = next((j for _, j in ch if json.loads(j).get("is_default")), ch[0][1] if ch else None)
        return gr.update(visible=True), gr.update(visible=False), gr.update(choices=ch, value=defv)

    # ── Wire events ────────────────────────────────────────────────────────────
    LOAD_OUT = [login_view, app_view, auth_state, user_display, sessions_radio]
    demo.load(on_load, [], LOAD_OUT)

    LOGIN_OUT = [login_view, app_view, auth_state, user_display, sessions_radio, login_err]
    login_btn.click(do_login, [login_user, login_pass], LOGIN_OUT)
    login_user.submit(do_login, [login_user, login_pass], LOGIN_OUT)
    login_pass.submit(do_login, [login_user, login_pass], LOGIN_OUT)

    logout_btn.click(do_logout, [], [login_view, app_view, auth_state, user_display, login_user, login_pass])

    model_dd.change(on_model_change, [model_dd], [model_row_state])

    SEND_IN  = [msg_box, chatbot, session_state, model_row_state]
    SEND_OUT = [session_state, msg_box, placeholder, chatbot, chart_html]
    send_btn.click(on_send, SEND_IN, SEND_OUT)
    msg_box.submit(on_send, SEND_IN, SEND_OUT)

    new_btn.click(on_new_chat, [],
                  [session_state, sessions_radio, msg_box, placeholder, chatbot, chart_html])
    refresh_btn.click(refresh_sessions, [], [sessions_radio])
    sessions_radio.change(on_select_session, [sessions_radio, session_state],
                          [session_state, placeholder, chatbot, chart_html])

    settings_btn.click(show_settings, [], [chat_view, settings_view, providers_df, models_df])
    back_btn.click(hide_settings, [], [chat_view, settings_view, model_dd])

    # Admin
    save_prov.click(lambda n,u,e,k: (admin_upsert_prov(n,u,e,k), admin_providers()),
                    [s_pn,s_pu,s_pe,s_pk], [settings_msg, providers_df])
    test_prov.click(lambda n: admin_test(n.strip()), [test_name], [settings_msg])
    add_model.click(lambda p,m,d,f,df: (admin_add_model(p,m,d,f,df), admin_models()),
                    [s_mp,s_mi,s_md,s_mf,s_md2], [settings_msg, models_df])
    ref_admin.click(lambda: (admin_providers(), admin_models()), [], [providers_df, models_df])


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        theme=gr.themes.Soft(),
        css=CSS,
        allowed_paths=[DL_DIR, "/app/docs"],
    )
