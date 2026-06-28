-- PPM Data Warehouse Initialization Script
-- This script creates the necessary schemas and databases

-- Create schemas for different data layers in ppm_datawarehouse
-- raw_jira schema will be created by dlt automatically
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mart;

-- Grant permissions to ppm_user
GRANT ALL PRIVILEGES ON SCHEMA staging TO ppm_user;
GRANT ALL PRIVILEGES ON SCHEMA core TO ppm_user;
GRANT ALL PRIVILEGES ON SCHEMA mart TO ppm_user;

-- Create additional databases for Mage AI, Metabase, and CloudBeaver
SELECT 'CREATE DATABASE mage_metadata'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mage_metadata')\gexec

SELECT 'CREATE DATABASE metabase'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'metabase')\gexec

SELECT 'CREATE DATABASE cloudbeaver'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'cloudbeaver')\gexec

-- Create extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

---- Schema documentation
--COMMENT ON SCHEMA staging IS 'Staging layer - cleaned and typed data from raw sources';
--COMMENT ON SCHEMA core IS 'Core layer - business logic and transformations';
--COMMENT ON SCHEMA mart IS 'Mart layer - user-facing data marts for analytics';


create schema if not exists public;
GRANT ALL PRIVILEGES ON SCHEMA public TO ppm_user;

CREATE FUNCTION public.safe_json_text_extract(json_text text, json_path text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN trim('"' from jsonb_path_query_first(json_text::jsonb, json_path::jsonpath)::text);
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;  -- Return NULL on any error instead of crashing
END;
$$;
GRANT EXECUTE ON FUNCTION public.safe_json_text_extract(text, text) TO ppm_user;