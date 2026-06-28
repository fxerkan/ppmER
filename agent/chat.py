"""PPM Data Stack - AI Chat Agent with tool calling."""
import os, json, subprocess
import gradio as gr
import psycopg2
from openai import OpenAI

API_KEY = os.getenv("OPENAI_API_KEY", "") or ""
client = OpenAI(
    api_key=API_KEY if API_KEY else "no-key",
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)
MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")
MISSING_KEY_MSG = (
    "⚠️ **AI Assistant is not configured.**\n\n"
    "To use this assistant, set `OPENAI_API_KEY` in your `.env` file.\n\n"
    "Get a free API key from:\n"
    "- [DeepSeek](https://platform.deepseek.com/) — generous free tier\n"
    "- [OpenAI](https://platform.openai.com/) — paid\n"
    "- Or run a local model with [Ollama](https://ollama.com/)\n\n"
    "Then restart the agent container: `docker restart ppm-agent`"
)

def get_db():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "ppm_datawarehouse"),
        user=os.getenv("POSTGRES_USER", "ppm_user"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_db",
            "description": "Run a read-only SQL query against the PPM data warehouse (PostgreSQL). Use this to explore data, check metrics, or answer questions about projects, issues, and worklogs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL SELECT query to execute"}
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_schemas",
            "description": "List all schemas and tables in the PPM data warehouse",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dbt_models",
            "description": "List all available dbt models organized by layer (staging, core, marts)",
            "parameters": {"type": "object", "properties": {}}
        }
    },
]

def query_db(sql: str) -> str:
    try:
        conn = get_db()
        cur = conn.cursor()
        # Only allow SELECT for safety
        if not sql.strip().upper().startswith("SELECT"):
            return "Error: Only SELECT queries are allowed."
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(100)
        conn.close()
        if not rows:
            return "No results."
        header = " | ".join(cols)
        sep = " | ".join(["---"] * len(cols))
        body = "\n".join(" | ".join(str(v) for v in row) for row in rows)
        return f"| {header} |\n| {sep} |\n" + "\n".join(f"| {r} |" for r in body.split("\n"))
    except Exception as e:
        return f"DB Error: {e}"

def list_schemas() -> str:
    return query_db("""
        SELECT table_schema, table_name,
               pg_size_pretty(pg_total_relation_size(quote_ident(table_schema)||'.'||quote_ident(table_name))) as size
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
        ORDER BY table_schema, table_name
    """)

def list_dbt_models() -> str:
    import os
    models = []
    dbt_path = "/dbt/models"
    if not os.path.exists(dbt_path):
        return "dbt models directory not found at /dbt/models"
    for root, dirs, files in os.walk(dbt_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if f.endswith('.sql'):
                rel = os.path.relpath(os.path.join(root, f), dbt_path)
                models.append(rel)
    return "\n".join(sorted(models))

def call_tool(name: str, args: dict) -> str:
    if name == "query_db":
        return query_db(args["sql"])
    if name == "list_schemas":
        return list_schemas()
    if name == "list_dbt_models":
        return list_dbt_models()
    return f"Unknown tool: {name}"

def chat(message: str, history: list) -> str:
    if not API_KEY:
        return MISSING_KEY_MSG
    messages = [{"role": "system", "content": """You are a PPM Data Stack assistant. You help Project & Portfolio Management teams analyze their Jira data.

You have access to:
- query_db: Run SQL queries against the PostgreSQL data warehouse
- list_schemas: See all tables and schemas
- list_dbt_models: See all available dbt transformation models

The data warehouse contains:
- staging schema: raw Jira data (issues, projects, users, worklogs, subtasks, links)
- core schema: dimension and fact tables (dim_projects, dim_issues, dim_users, fact_worklogs, fact_issues)
- mart schema: business-ready aggregations (mart_portfolio_dashboard, agg_project_health, rpt_missing_effort)

Always use list_schemas first if you're unsure what tables exist. Write clean SQL."""}]

    for h in history:
        if isinstance(h, dict):
            messages.append({"role": h["role"], "content": h["content"]})
        else:
            messages.append({"role": "user", "content": h[0]})
            if h[1]:
                messages.append({"role": "assistant", "content": h[1]})
    messages.append({"role": "user", "content": message})

    # Agentic loop with tool calling
    for _ in range(5):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        msg = resp.choices[0].message

        if not msg.tool_calls:
            return msg.content or ""

        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]})

        for tc in msg.tool_calls:
            result = call_tool(tc.function.name, json.loads(tc.function.arguments))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return "Max tool calls reached."

with gr.Blocks(title="PPM Data Stack Agent") as demo:
    gr.Markdown("# PPM Data Stack AI Agent\nChat with your Jira project data. Ask questions in natural language.")
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("""**Available Tools**
- `query_db` — run SQL
- `list_schemas` — explore tables
- `list_dbt_models` — see models

**Example questions:**
- How many open issues per project?
- Show me the top 10 users by logged hours this month
- Which projects have the most overdue tasks?
- List all epic names and their status
""")
        with gr.Column(scale=3):
            gr.ChatInterface(chat)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
