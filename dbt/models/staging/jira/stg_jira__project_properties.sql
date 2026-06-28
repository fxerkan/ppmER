{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="property_id",
    )
}}

{#
  Project Properties Staging Model - OPTIMIZED VERSION

  Transforms raw project properties from the optimized DLT pipeline:
  - Source data has properties stored as JSON (one row per project)
  - This model unnests/flattens to one row per property (for compatibility)
  - Handles JSON parsing and value extraction
  - Standardizes property names (BusinessLine -> Business Line, IT_Domain -> IT Domain)
  - Categorizes properties by type (portfolio, jira_software, etc.)

  Performance: Works with optimized source (476 rows with JSON) vs old source (5682 flattened rows)
#}
with
    source as (select * from {{ source("raw_jira", "project_properties") }}),

    -- Parse JSON and extract key-value pairs
    -- Uses PostgreSQL json_each_text to convert JSON object to key-value rows
    properties_unnested as (
        select
            id as source_id,
            project_id as project_id,
            project_key,
            properties,
            property_count,
            extracted_at,
            _dlt_load_id,
            _dlt_id,
            _etl_date,
            -- Extract each property key-value pair from the JSON
            kv.key as property_key,
            kv.value as raw_value
        from source, lateral json_each_text(properties::json) as kv
        where properties is not null
    ),

    -- Generate unique property ID and clean values
    cleaned as (
        select
            -- Generate unique property_id (compatible with old format)
            project_id || '_' || property_key as property_id,
            project_id,
            project_key,
            property_key,
            raw_value,

            -- Convert JSON/boolean values to clean format
            case
                -- Handle null values and empty arrays
                when
                    raw_value is null
                    or trim(raw_value) = ''
                    or lower(trim(raw_value)) = 'null'
                    or trim(raw_value) = '[]'
                then null
                -- Handle boolean strings
                when lower(trim(raw_value)) = 'true'
                then 'true'
                when lower(trim(raw_value)) = 'false'
                then 'false'
                -- Handle nested JSON objects (like {"jswSelectedBoardType": "scrum"})
                -- Extract the inner value if it's a simple key-value JSON
                when raw_value like '{{ '{' }}%{{ '} ' }}'
                then
                    coalesce(
                        -- Try to extract first value from nested JSON
                        (
                            select json_object_agg(k, v)::text
                            from json_each_text(raw_value::json) as nested(k, v)
                            limit 1
                        ),
                        raw_value
                    )
                -- Plain text/numeric values
                else raw_value
            end as cleaned_value,

            -- Flag to indicate if value is a JSON object
            case
                when raw_value like '{{ '{' }}%{{ '} ' }}' then true else false
            end as is_json_value,

            -- Flag for null/none values
            case
                when
                    raw_value is null
                    or trim(raw_value) = ''
                    or lower(trim(raw_value)) = 'null'
                    or trim(raw_value) = '[]'
                then true
                else false
            end as is_null_value,

            -- Flag for boolean values
            case
                when lower(trim(raw_value)) in ('true', 'false') then true else false
            end as is_boolean_value,

            extracted_at,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from properties_unnested
    ),

    -- Extract property category and clean property names
    categorized as (
        select
            *,
            -- Categorize property types based on prefix
            case
                when property_key like 'pp-%'
                then 'portfolio'
                when property_key like 'jira%'
                then 'jira_integration'
                when property_key like 'jsw%'
                then 'jira_software'
                when property_key like 'code-link%'
                then 'dev_integration'
                when property_key like 'testrail%'
                then 'test_integration'
                when property_key like 'msTeams%'
                then 'teams_integration'
                else 'other'
            end as property_category,

            -- Remove pp- prefix for portfolio properties
            case
                when property_key like 'pp-%'
                then replace(property_key, 'pp-', '')
                else property_key
            end as property_name_raw
        from cleaned
    ),

    -- Standardize property names and parse complex values
    standardized as (
        select
            *,
            -- Standardize common property name variations to consistent format
            case
                -- Business Line variations
                when lower(property_name_raw) = 'businessline'
                then 'Business Line'
                when lower(property_name_raw) = 'business line'
                then 'Business Line'
                -- IT Domain variations
                when lower(property_name_raw) = 'it_domain'
                then 'IT Domain'
                when lower(property_name_raw) = 'it domain'
                then 'IT Domain'
                when lower(property_name_raw) = 'itdomain'
                then 'IT Domain'
                -- Product Group variations
                when lower(property_name_raw) = 'productgroup'
                then 'Product Group'
                when lower(property_name_raw) = 'product group'
                then 'Product Group'
                -- Customer variations
                when lower(property_name_raw) = 'customer'
                then 'Customer'
                -- Hosting variations
                when lower(property_name_raw) = 'hosting'
                then 'Hosting'
                -- ID
                when lower(property_name_raw) = 'id'
                then 'ID'
                -- Keep original for others
                else property_name_raw
            end as property_name_clean,

            -- For nested JSON values, extract the actual value
            case
                when is_json_value and cleaned_value is not null
                then
                    -- For nested JSON like {"key": "value"}, extract the value part
                    coalesce(
                        -- Try to extract first value from the JSON object
                        (
                            select v
                            from json_each_text(cleaned_value::json) as nested(k, v)
                            limit 1
                        ),
                        cleaned_value
                    )
                when is_boolean_value
                then cleaned_value
                when is_null_value
                then null
                else cleaned_value
            end as parsed_value
        from categorized
    )

-- Filter to only include the specified portfolio properties
select
    property_id,
    project_id,
    project_key,
    property_key,
    property_name_clean,
    property_category,
    raw_value,
    cleaned_value,
    parsed_value,
    is_json_value,
    is_null_value,
    is_boolean_value,
    extracted_at,
    _dlt_load_id,
    _dlt_id,
    _etl_date
from standardized
where
    -- Only include these specific portfolio properties
    property_name_clean in (
        'Application Management Distribution Effort',
        'Business Line',
        'Customer',
        'DevOps.ProjectSelectedDeploymentApps',
        'Financial Report Display',
        'Financial Code',
        'Hosting',
        'ID',
        'IT Domain',
        'ITOPS Distribution Effort',
        'Information Security Distribution Effort',
        'L1 Distribution Effort',
        'L2 Distribution Effort',
        'Open.Closed',
        'Product',
        'Product Group',
        'Subject to App Management Distribution',
        'Subject to ITOPS Distribution',
        'Subject to L1 Distribution',
        'Tribe'
    )
order by project_id, property_key
