{{
  config(
    materialized='view',
    schema='staging',
    tags=['jira', 'staging'],
    unique_key='custom_field_id',
    on_schema_change='sync_all_columns'
  )
}}

{#
  Issue Custom Fields Staging Model - OPTIMIZED VERSION

  Transforms raw issue custom fields from the optimized DLT pipeline:
  - Source data has custom fields stored as JSON (one row per issue)
  - This model unnests/flattens to one row per custom field per issue
  - Handles JSON parsing and value extraction
  - Maps field IDs to human-readable names
  - Extracts nested values from complex custom field types

  Performance: Works with optimized source (~7K rows with JSON) vs old source (~106K flattened rows)
#}

with source as (
    select * from {{ source('raw_jira', 'issue_custom_fields') }}
),

-- Filter to valid JSON only (PostgreSQL 12+ has is_valid_json, but we'll use try-catch approach)
valid_json_source as (
    select
        id,
        issue_key,
        custom_fields,
        field_count,
        extracted_at,
        _dlt_load_id,
        _dlt_id,
        _etl_date
    from source
    where custom_fields is not null
      -- Validate JSON by attempting to cast and checking for basic structure
      and custom_fields::text ~ '^\{.*\}$'
      -- Additional safety: try to ensure it's valid JSON by checking it starts and ends correctly
      and length(trim(custom_fields)) > 2
),

-- Parse JSON and extract custom field key-value pairs
custom_fields_unnested as (
    select
        id as source_id,
        issue_key,
        custom_fields,
        field_count,
        extracted_at,
        _dlt_load_id,
        _dlt_id,
        _etl_date,
        -- Extract each custom field key-value pair from the JSON
        kv.key as field_id,
        kv.value as raw_value
    from valid_json_source,
    lateral json_each_text(custom_fields::json) as kv
),

-- Generate unique ID and clean values
cleaned as (
    select
        -- Generate unique custom_field_id
        issue_key || '_' || field_id as custom_field_id,
        issue_key,
        field_id,
        raw_value,

        -- Map field IDs to human-readable names
        case field_id
            when 'customfield_10037' then 'Story Points'
            when 'customfield_10014' then 'Epic Link'
            when 'customfield_10100' then 'Acceptance Criteria'
            when 'customfield_10467' then 'ITOPS Approver'
            when 'customfield_10449' then 'Info Security Approver'
            when 'customfield_10306' then 'Record Type'
            when 'customfield_10415' then 'FirmaX Ops Approvers'
            when 'customfield_10176' then 'New Sprint Issue'
            when 'customfield_10284' then 'IT/Other'
            when 'customfield_10153' then 'IT Approvers'
            when 'customfield_10019' then 'Rank'
            when 'customfield_10126' then 'Approvers'
            when 'customfield_10000' then 'Development'
            when 'customfield_10097' then 'Spike Type'
            when 'customfield_10150' then 'Defect Detection Process'
            when 'customfield_10073' then 'Bug Detection Environment'
            when 'customfield_11915' then 'Project'
            when 'customfield_10129' then 'Product Choice'
            when 'customfield_10020' then 'Sprint'
            when 'customfield_10349' then 'Sep 2024 Planned Effort'
            else field_id
        end as field_name,

        -- Determine field type
        case
            -- Numeric fields
            when field_id in ('customfield_10037', 'customfield_10349') then 'numeric'
            -- Text/String fields
            when field_id in ('customfield_10014', 'customfield_10019', 'customfield_11915') then 'text'
            -- Rich text/Document fields
            when field_id in ('customfield_10100') then 'document'
            -- User/Person fields
            when field_id in ('customfield_10467', 'customfield_10449', 'customfield_10415',
                              'customfield_10153', 'customfield_10126') then 'user'
            -- Array/List fields
            when field_id in ('customfield_10020') then 'array'
            -- Other
            else 'other'
        end as field_type,

        -- Parse the value based on field type and structure
        case
            -- Handle null/empty values
            when raw_value is null
                or trim(raw_value) = ''
                or lower(trim(raw_value)) = 'null'
                or trim(raw_value) = '[]' then null

            -- Handle simple numeric values (Story Points, Planned Effort)
            when field_id in ('customfield_10037', 'customfield_10349')
                and raw_value ~ '^[0-9]+\.?[0-9]*$' then raw_value

            -- Handle simple text values (Epic Link, Rank)
            when field_id in ('customfield_10014', 'customfield_10019') then raw_value

            -- Skip Development field (customfield_10000) - contains invalid JSON format
            when field_id = 'customfield_10000' then null

            -- Handle Acceptance Criteria (customfield_10100) - Extract text from doc structure
            when field_id = 'customfield_10100' and raw_value like '%"text":%' then
                -- Extract all text values from the document structure
                (select string_agg(elem->>'text', ' ')
                 from jsonb_path_query(raw_value::jsonb, '$.content[*].content[*]') as elem
                 where elem->>'text' is not null)

            -- Handle User/Approver fields (arrays of user objects) - Extract accountId values
            when field_id in ('customfield_10467', 'customfield_10449', 'customfield_10415',
                              'customfield_10153', 'customfield_10126')
                 and raw_value like '[%' then
                -- Extract comma-separated accountIds from array
                (select string_agg(elem->>'accountId', ', ')
                 from jsonb_array_elements(raw_value::jsonb) as elem)

            -- Handle Sprint field (customfield_10020) - Extract sprint names from array
            when field_id = 'customfield_10020' and raw_value like '[%' then
                (select string_agg(elem->>'name', ', ')
                 from jsonb_array_elements(raw_value::jsonb) as elem)

            -- Handle Product Choice (customfield_10129) - Extract value field
            when field_id = 'customfield_10129' and raw_value like '[%' then
                (select string_agg(elem->>'value', ', ')
                 from jsonb_array_elements(raw_value::jsonb) as elem)

            -- Handle Project field (customfield_11915) - Extract value field (can be array or string)
            when field_id = 'customfield_11915' then
                case
                    when raw_value like '[%' then
                        (select string_agg(elem->>'value', ', ')
                         from jsonb_array_elements(raw_value::jsonb) as elem)
                    else raw_value
                end

            -- Handle other select list fields - try to extract 'value' field
            when field_id in ('customfield_10306', 'customfield_10284', 'customfield_10097',
                              'customfield_10073', 'customfield_10150', 'customfield_10176')
                 and raw_value like '{{ '{' }}%' then
                (raw_value::json->>'value')

            -- For any other JSON objects, try common extraction patterns
            when raw_value like '{{ '{' }}%{{ '}' }}' and raw_value not like '%=%' then
                coalesce(
                    (raw_value::json->>'name'),
                    (raw_value::json->>'displayName'),
                    (raw_value::json->>'value'),
                    raw_value
                )

            -- Plain values
            else raw_value
        end as field_value_parsed,

        -- Flag if value is JSON
        case
            when raw_value like '{{ '{' }}%{{ '}' }}' or raw_value like '[%]' then true
            else false
        end as is_json_value,

        -- Flag if value is null
        case
            when raw_value is null
                or trim(raw_value) = ''
                or lower(trim(raw_value)) = 'null'
                or trim(raw_value) = '[]' then true
            else false
        end as is_null_value,

        -- Extract ID values for specific fields (Product Choice, Project, Sprint)
        case
            -- Product Choice ID (customfield_10129)
            when field_id = 'customfield_10129' and raw_value like '[%' then
                (select string_agg(elem->>'id', ', ')
                 from jsonb_array_elements(raw_value::jsonb) as elem)
            -- Project ID (customfield_11915)
            when field_id = 'customfield_11915' and raw_value like '[%' then
                (select string_agg(elem->>'id', ', ')
                 from jsonb_array_elements(raw_value::jsonb) as elem)
            -- Sprint ID (customfield_10020)
            when field_id = 'customfield_10020' and raw_value like '[%' then
                (select string_agg((elem->>'id')::text, ', ')
                 from jsonb_array_elements(raw_value::jsonb) as elem)
            else null
        end as field_value_id,

        extracted_at,
        _dlt_load_id,
        _dlt_id,
        _etl_date
    from custom_fields_unnested
)

select
    custom_field_id,
    issue_key,
    field_id,
    field_name,
    field_type,
    raw_value,
    field_value_parsed,
    field_value_id,
    is_json_value,
    is_null_value,
    extracted_at,
    _dlt_load_id,
    _dlt_id,
    _etl_date
from cleaned
order by issue_key, field_id
