#!/usr/bin/env python3
"""
MCP server for PPM Data Stack.
Exposes tools: query_db, list_schemas, list_dbt_models, run_pipeline.

Claude Code config (.claude/mcp.json):
{
  "mcpServers": {
    "ppm-data-stack": {
      "command": "python",
      "args": ["/path/to/agent/mcp_server.py"],
      "env": {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "15432",
        "POSTGRES_DB": "ppm_datawarehouse",
        "POSTGRES_USER": "ppm_user",
        "POSTGRES_PASSWORD": "your_password"
      }
    }
  }
}
"""
import sys, json, os
import psycopg2

def get_db():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 15432)),
        dbname=os.getenv("POSTGRES_DB", "ppm_datawarehouse"),
        user=os.getenv("POSTGRES_USER", "ppm_user"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )

def query_db(sql: str) -> str:
    if not sql.strip().upper().startswith("SELECT"):
        return "Error: Only SELECT queries allowed"
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(200)
        conn.close()
        if not rows:
            return "No rows returned"
        lines = [",".join(cols)]
        lines += [",".join(str(v) for v in row) for row in rows]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"

def list_schemas() -> str:
    return query_db("""SELECT table_schema, table_name FROM information_schema.tables
                       WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
                       ORDER BY table_schema, table_name""")

def list_dbt_models() -> str:
    dbt_path = os.getenv("DBT_PATH", "/dbt/models")
    if not os.path.exists(dbt_path):
        dbt_path = os.path.join(os.path.dirname(__file__), "..", "dbt", "models")
    results = []
    for root, dirs, files in os.walk(dbt_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            if f.endswith('.sql'):
                results.append(os.path.relpath(os.path.join(root, f), dbt_path))
    return "\n".join(sorted(results))

TOOLS = {
    "query_db": {
        "description": "Run a SELECT SQL query against the PPM PostgreSQL data warehouse",
        "inputSchema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "SQL SELECT statement"}},
            "required": ["sql"]
        },
        "fn": lambda args: query_db(args["sql"])
    },
    "list_schemas": {
        "description": "List all schemas and tables in the PPM data warehouse",
        "inputSchema": {"type": "object", "properties": {}},
        "fn": lambda args: list_schemas()
    },
    "list_dbt_models": {
        "description": "List all dbt transformation models available",
        "inputSchema": {"type": "object", "properties": {}},
        "fn": lambda args: list_dbt_models()
    },
}

def handle(request: dict) -> dict:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "ppm-data-stack", "version": "1.0.0"},
            "capabilities": {"tools": {}}
        }}

    if method == "tools/list":
        tools = [{"name": k, "description": v["description"], "inputSchema": v["inputSchema"]} for k, v in TOOLS.items()]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    if method == "tools/call":
        name = request["params"]["name"]
        args = request["params"].get("arguments", {})
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Tool not found: {name}"}}
        result = TOOLS[name]["fn"](args)
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": result}]}}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle(req)
            print(json.dumps(resp), flush=True)
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}), flush=True)
