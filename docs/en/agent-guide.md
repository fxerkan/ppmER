# AI Agent Integration Guide

This guide covers connecting various AI agents to the PPM Data Stack for natural language data analysis.

---

## Built-in Chat Agent (Gradio)

The stack includes a ready-to-use chat UI at **http://localhost:7860**.

It works with any OpenAI-compatible API. Set in `.env`:

```env
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1   # or any compatible endpoint
OPENAI_MODEL=gpt-4o-mini
```

---

## Claude Code Setup (MCP Server)

The included `agent/mcp_server.py` implements the Model Context Protocol (MCP) for direct integration with Claude Code or Cursor.

### Configuration

Add to your Claude Code MCP config (`~/.claude/mcp.json` or project `.claude/mcp.json`):

```json
{
  "mcpServers": {
    "ppm-data-stack": {
      "command": "python",
      "args": ["/absolute/path/to/jira-ppm-data-stack/agent/mcp_server.py"],
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
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `query_db` | Run a SELECT SQL query against the data warehouse |
| `list_schemas` | List all schemas and tables |
| `list_dbt_models` | List all dbt transformation models |

### Example Usage in Claude Code

Once MCP is configured, Claude Code can use these tools directly:
```
> Which projects have the most open issues?
Claude will call query_db with the appropriate SQL and return results.
```

---

## Using Anthropic Claude API (OpenAI-Compatible)

Point the chat agent to Anthropic's OpenAI-compatible endpoint:

```env
OPENAI_API_KEY=sk-ant-your-anthropic-api-key
OPENAI_BASE_URL=https://api.anthropic.com/v1
OPENAI_MODEL=claude-3-5-haiku-20241022
```

Note: Anthropic's OpenAI-compatible endpoint supports tool calling, which the chat agent uses.

---

## Using OpenAI (GPT)

Default configuration. Set:
```env
OPENAI_API_KEY=sk-your-openai-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini          # cheapest option, works well
# or: gpt-4o for better reasoning
```

---

## Using Google Gemini

Gemini has an OpenAI-compatible endpoint:

```env
OPENAI_API_KEY=your-gemini-api-key
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_MODEL=gemini-2.0-flash
```

Get an API key from: https://aistudio.google.com/apikey

---

## Using Local Ollama (No API Key)

Run models locally with zero cost. Install Ollama from https://ollama.ai then:

```bash
ollama pull qwen2.5-coder:7b   # good for SQL tasks
```

```env
OPENAI_API_KEY=ollama           # placeholder, not used
OPENAI_BASE_URL=http://host.docker.internal:11434/v1
OPENAI_MODEL=qwen2.5-coder:7b
```

Note: Local models may be slower and less accurate for complex SQL generation.

---

## Example Prompts by Use Case

### Portfolio Health Check
```
"Give me a one-line status for each active project: total issues, open issues, hours logged this month, and whether the workload seems balanced."
```

### Missing Effort Audit
```
"Find all issues that are In Progress or In Review, have a Story Points value > 0, but have zero worklogs in the last 14 days. Group by assignee."
```

### Sprint Velocity
```
"Calculate the average number of story points completed per week over the last 8 weeks, broken down by project."
```

### User Workload Analysis
```
"Who is over-allocated this month (more than 160 hours logged)? Who is under-allocated (less than 80 hours)?"
```

### Issue Age Report
```
"Show me the 20 oldest open issues across all projects, with their assignee, priority, and how many days they've been open."
```

### Custom Field Analysis
```
"List all issues where the custom field 'story_points' is null but the issue type is Story or Task, and status is not Done."
```

---

## Direct SQL via MCP

You can also use the MCP server for precise SQL queries:

```sql
-- Example: find projects with no activity in 30 days
SELECT p.project_name, MAX(w.started_at) as last_activity
FROM core.dim_projects p
LEFT JOIN core.fact_worklogs w ON p.project_key = w.project_key
GROUP BY p.project_name
HAVING MAX(w.started_at) < NOW() - INTERVAL '30 days'
   OR MAX(w.started_at) IS NULL
ORDER BY last_activity NULLS FIRST;
```

---

## Security Notes

- The MCP server and chat agent only allow `SELECT` queries — no writes, deletes, or DDL
- The Postgres user should have `SELECT` privileges only for production use
- API keys are stored in `.env` which is gitignored — never commit it
- For team use, consider running the stack behind a VPN or with Metabase user authentication
