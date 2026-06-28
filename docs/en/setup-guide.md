# Setup Guide

This guide is written for PMO/business users who may not be familiar with Docker or command-line tools. Follow each step in order.

---

## Step 1: Prerequisites

You need two things installed:

### Docker Desktop
1. Go to https://www.docker.com/products/docker-desktop/
2. Download for your operating system (Mac or Windows)
3. Install and start Docker Desktop
4. In Docker Desktop settings, allocate at least **4GB RAM** to Docker
   - Mac: Docker Desktop > Settings > Resources > Memory > 4GB+
   - Windows: Docker Desktop > Settings > Resources > Memory > 4GB+

### Git (to clone the project)
- Mac: Open Terminal, type `git --version`. If not installed, macOS will prompt you to install it.
- Windows: Download from https://git-scm.com/download/win

---

## Step 2: Getting Your Jira API Token

1. Log into Jira at https://your-company.atlassian.net
2. Click your profile picture (top right) > **Manage account**
3. Go to **Security** tab
4. Click **Create and manage API tokens**
5. Click **Create API token**
6. Give it a name like "PPM Data Stack"
7. Click **Create** and **copy the token** — you won't see it again

---

## Step 3: Download and Configure

Open Terminal (Mac) or Command Prompt (Windows):

```bash
# Clone the project
git clone https://github.com/fxerkan/jira-ppm-data-stack.git
cd jira-ppm-data-stack

# Copy the example configuration
cp .env.example .env
```

Now open the `.env` file in any text editor (Notepad, TextEdit, VS Code) and fill in:

```
JIRA_SUBDOMAIN=your-company        # The part before .atlassian.net
JIRA_EMAIL=you@yourcompany.com     # Your Jira login email
JIRA_API_TOKEN=<paste-token-here>  # The token from Step 2
POSTGRES_PASSWORD=choose-a-strong-password
CB_ADMIN_PASSWORD=choose-admin-password
```

Save the file.

---

## Step 4: Start the Stack

In your terminal (make sure you're in the project folder):

```bash
docker-compose up -d
```

This will download all required Docker images (~2-3 GB) and start the services. On first run, this takes 5-10 minutes. You can check progress with:

```bash
docker-compose ps
```

All services should show `Up` or `healthy` after a few minutes.

---

## Step 5: Run Your First Data Load

Open your browser and go to: **http://localhost:6789**

This is Mage AI, the pipeline orchestrator.

1. In the left sidebar, click **Pipelines**
2. Find `master_initial_jira` — this loads ALL your Jira history
3. Click the pipeline, then click **Run pipeline now**
4. Watch the logs — it may take 10-60 minutes depending on how much Jira data you have

For daily updates (after the initial load), use `master_daily_jira` instead.

---

## Step 6: Open Metabase and Create Your First Dashboard

1. Go to http://localhost:3000
2. Click **Get started**
3. Create an admin account (this is local only)
4. On the "Add your data" step, select **PostgreSQL**:
   - Host: `postgres`
   - Port: `5432`
   - Database name: `ppm_datawarehouse`
   - Username: `ppm_user`
   - Password: (what you set in `.env` as `POSTGRES_PASSWORD`)
5. Click **Connect database**

### Creating your first question (report):

1. Click **+ New > Question**
2. Select your `ppm_datawarehouse` database
3. Choose **Native query** (SQL)
4. Paste this query:

```sql
SELECT
    project_key,
    COUNT(*) as total_issues,
    COUNT(CASE WHEN status_category != 'Done' THEN 1 END) as open_issues
FROM core.fact_issues
GROUP BY project_key
ORDER BY open_issues DESC;
```

5. Click **Run** to see results
6. Click **Save** to save as a question
7. Add to a new dashboard

See [metabase/README.md](../../metabase/README.md) for 5 ready-to-use dashboard queries.

---

## Step 7: Use the AI Chat Agent

1. Go to http://localhost:7860
2. Type a question in the chat box, for example:
   - "How many open issues does each project have?"
   - "Show me users who haven't logged any hours this week"
   - "Which epics are at risk of missing their deadline?"

The AI agent will automatically query your database and return results in plain language with tables.

---

## Daily Usage

After the initial setup, your typical workflow is:

1. **Pipelines run automatically** — Mage AI is configured to run `master_daily_jira` every night
2. **Check dashboards in Metabase** — open http://localhost:3000 each morning
3. **Ask questions in the AI agent** — http://localhost:7860 for ad-hoc analysis

To stop the stack: `docker-compose down`
To restart it: `docker-compose up -d`

---

## Troubleshooting

**"docker-compose: command not found"**
Try `docker compose up -d` (without the hyphen — newer Docker versions use this syntax).

**Services show "Exiting" status**
Check logs: `docker-compose logs <service-name>` (e.g., `docker-compose logs mage`)

**Jira pipeline fails with "401 Unauthorized"**
Your API token or email in `.env` is incorrect. Double-check and run `docker-compose restart mage`.

**Can't connect to Metabase database**
Make sure the pipeline has run at least once. The `core` schema won't exist until dbt transformations have run.

**Running out of disk space**
Docker images and data take ~5-10GB. Run `docker system prune` to clean up unused images.
