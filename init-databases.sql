-- Initialize databases for all three companies
-- This script runs automatically when PostgreSQL container starts for the first time

CREATE DATABASE sammys_db;
CREATE DATABASE tonys_db;
CREATE DATABASE zuckers_db;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE sammys_db TO orderbot;
GRANT ALL PRIVILEGES ON DATABASE tonys_db TO orderbot;
GRANT ALL PRIVILEGES ON DATABASE zuckers_db TO orderbot;
