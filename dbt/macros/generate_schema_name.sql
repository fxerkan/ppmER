{% macro generate_schema_name(custom_schema_name, node) -%}
    {#
        This macro overrides the default dbt schema generation behavior.
        Instead of prefixing custom_schema with target schema (e.g., staging_staging),
        it uses the custom_schema directly (e.g., staging).

        If no custom_schema is specified, it falls back to the target schema.
    #}
    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%} {{ default_schema }}
    {%- else -%} {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
