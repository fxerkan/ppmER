# SharePoint DLT Pipelines

This directory contains DLT (Data Load Tool) pipelines for extracting data from SharePoint Online lists and loading them into PostgreSQL.

## Overview

The SharePoint DLT pipelines extract data from the following SharePoint lists:

| SharePoint List | DLT Script | Target Table | Description |
|----------------|------------|--------------|-------------|
| Projects | `shrp_projects.py` | `raw_sharepoint.projects` | Master project registry mapping Jira project IDs |
| Proje Inv | `shrp_proje_inv.py` | `raw_sharepoint.proje_inv` | Project inventory with status, timeline, and risk info |
| Proje Risks | `shrp_proje_risks.py` | `raw_sharepoint.proje_risks` | Project risk tracking entries |
| Issue Type | `shrp_issue_type.py` | `raw_sharepoint.issue_type` | Jira issue type classifications (Expensed/Capitalized) |
| Issue Type Inventory | `shrp_issue_type_inventory.py` | `raw_sharepoint.issue_type_inventory` | Task type definitions with descriptions |
| PBI Info | `shrp_pbi_info.py` | `raw_sharepoint.pbi_info` | Power BI project/team mapping |

## Features

- **Automatic Pagination**: Handles large lists with 5000+ items
- **Dynamic Schema Discovery**: Automatically detects and handles all list fields
- **Schema Evolution**: Creates tables if not exist, handles field additions/removals
- **Multiple Authentication Methods**: Supports MSAL + Microsoft Graph API
- **Type Normalization**: Converts SharePoint field types to database-friendly formats

## Authentication Setup

### MSAL + Microsoft Graph API (Recommended)

This is the recommended approach for automated pipelines using Azure AD app registration with Microsoft Graph API.

#### Prerequisites

You need an Azure AD App Registration with the following:
- **Tenant ID**: Your Azure AD tenant identifier
- **Client ID**: Application (client) ID from Azure AD
- **Client Secret**: A client secret created for the application

#### Required API Permissions

Configure the following Microsoft Graph API permissions (Application type):
- `Sites.Read.All` - Read items in all site collections

#### Environment Variables

Configure the following environment variables in `.env`:

```bash
SHAREPOINT__SITE_URL="https://yourcompany.sharepoint.com/sites/ProjectInventory"
SHAREPOINT__TENANT_ID="your-tenant-id"
SHAREPOINT__CLIENT_ID="your-client-id"
SHAREPOINT__CLIENT_SECRET="your-client-secret"
```

## Running the Pipelines

### Via Mage AI (Recommended)

The pipelines are integrated with Mage AI. Use the following pipelines:

| Pipeline | Schedule | Description |
|----------|----------|-------------|
| **master_sharepoint** | Daily at 08:00 UTC | Standalone SharePoint data load |
| **master_daily_jira** | Daily at 09:00 UTC | Combined Jira + SharePoint data load |

Run via Mage UI at http://localhost:6789 or via CLI:

```bash
# Run standalone SharePoint pipeline
docker exec ppm-mage mage run default_repo master_sharepoint

# Run combined daily pipeline (includes SharePoint)
docker exec ppm-mage mage run default_repo master_daily_jira
```

### Via Command Line

Run individual pipelines directly:

```bash
# Initial load (full replace)
docker exec ppm-dlt python /app/sharepoint/shrp_projects.py --mode=initial

# Daily incremental load (merge/upsert)
docker exec ppm-dlt python /app/sharepoint/shrp_projects.py --mode=daily
```

## Pipeline Modes

### Initial Mode (`--mode=initial`)

- **Purpose**: Full historical load
- **Write Disposition**: Replace (drops and recreates table)
- **Use Case**: First time setup, or when you want to rebuild the table from scratch

### Daily Mode (`--mode=daily`)

- **Purpose**: Incremental updates
- **Write Disposition**: Merge (upserts based on primary key `ID`)
- **Use Case**: Regular scheduled updates
- **Schema Evolution**: Automatically handles new/removed fields

## Architecture

### Module Structure

```
dlt/sharepoint/
├── __init__.py                      # Package initialization
├── sharepoint_auth.py               # Legacy authentication utilities
├── sharepoint_auth_msal.py          # MSAL + Graph API authentication
├── sharepoint_utils.py              # Data extraction utilities
├── shrp_projects.py                 # Projects pipeline
├── shrp_proje_inv.py                # Proje Inv pipeline
├── shrp_proje_risks.py              # Proje Risks pipeline
├── shrp_issue_type.py               # Issue Type pipeline
├── shrp_issue_type_inventory.py     # Issue Type Inventory pipeline
├── shrp_pbi_info.py                 # PBI Info pipeline
└── README.md                        # This file
```

### DBT Staging Models

After data extraction, the following dbt staging models transform the raw data:

| Staging Model | Description |
|---------------|-------------|
| `stg_sharepoint__projects` | Project registry with Jira ID mapping |
| `stg_sharepoint__proje_inv` | Project inventory with cleaned field names |
| `stg_sharepoint__proje_risks` | Project risks with status tracking |
| `stg_sharepoint__issue_type` | Issue types with expense classification |
| `stg_sharepoint__issue_type_inventory` | Task type definitions |
| `stg_sharepoint__pbi_info` | Power BI project/team mapping |

Run staging models via:
```bash
docker exec ppm-mage dbt run --select staging.sharepoint.* --profiles-dir /home/src/default_repo/dbt --project-dir /home/src/default_repo/dbt
```

## Field Type Mapping

SharePoint field types are automatically converted to database-friendly formats:

| SharePoint Type | Python Type | Notes |
|----------------|-------------|-------|
| Text | str | Single line of text |
| Note | str | Multiple lines of text |
| Number | int/float | Numeric values |
| DateTime | str (ISO 8601) | Converted to ISO format |
| Boolean | bool | Yes/No fields |
| Choice | str | Single choice value |
| MultiChoice | list[str] | Multiple choice values |
| User | str | Email or display name |
| Lookup | str | LookupValue extracted |
| URL | dict | Contains Description and Url (excluded from staging) |

## Troubleshooting

### Authentication Errors

**Problem**: `401 Unauthorized` or authentication failures

**Solution**:
1. Verify the Azure AD app registration has correct permissions
2. Check if the client secret has expired
3. Verify tenant ID, client ID, and client secret are correct
4. Ensure the app has admin consent for Graph API permissions

### List Not Found

**Problem**: `404 List not found`

**Solution**:
1. Verify the list title is exactly correct (case-sensitive)
2. Check if the list exists at the site URL
3. Verify the app has access to the site collection

### Permission Errors

**Problem**: `403 Forbidden`

**Solution**:
1. Verify the app has `Sites.Read.All` Graph API permission
2. Ensure admin consent has been granted
3. Check if the site has any additional access restrictions

## Data Dictionary

### projects

Maps Jira project IDs to SharePoint project metadata.

| Field | Type | Description |
|-------|------|-------------|
| id | varchar | SharePoint item ID |
| title | varchar | Project title/name |
| id_project | varchar | Jira project ID mapping |
| field_3 | varchar | Project type category |

### proje_inv

Detailed project inventory for executive reporting.

| Field | Type | Description |
|-------|------|-------------|
| id | varchar | SharePoint item ID |
| title | varchar | Project code (e.g., M0072) |
| field_1 | varchar | Project internal name |
| field_2 | varchar | Customer/brand name |
| field_4 | varchar | Product family |
| on_track_x002f_delayed | varchar | Tracking status (On Track/Delayed) |
| status_progress | text | Current progress notes |
| project_timeline | text | Timeline milestones |
| is_strategic_portfolio_x003fx | varchar | Strategic portfolio flag |
| escalation | double | Escalation count |

### issue_type

Maps Jira issue types to expense classifications.

| Field | Type | Description |
|-------|------|-------------|
| id | varchar | SharePoint item ID |
| title | varchar | Issue type name |
| field_1 | varchar | Expense classification (Expensed/Capitalized) |
| field_2 | double | Jira issue type ID |
| category | varchar | Category (SDLC Tasks, General Tasks, etc.) |
| active | varchar | Active status (Evet/Hayir) |

## Support and Resources

- **MSAL Python Documentation**: https://github.com/AzureAD/microsoft-authentication-library-for-python
- **Microsoft Graph API Reference**: https://learn.microsoft.com/en-us/graph/api/overview
- **DLT Documentation**: https://dlthub.com/docs
- **Azure AD App Registration**: https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app
