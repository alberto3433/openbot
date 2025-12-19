"""
Migrate SQLite databases to PostgreSQL.

Usage:
    python migrate_to_postgres.py

This script migrates all three SQLite databases (Sammy's, Tony's, Zucker's)
to their respective PostgreSQL databases.
"""

import os
import sys
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sandwich_bot.models import Base

# PostgreSQL connection info
PG_USER = "orderbot"
PG_PASSWORD = "orderbot123"
PG_HOST = "localhost"
PG_PORT = "5432"

# Migration mapping: SQLite file -> PostgreSQL database
MIGRATIONS = [
    {
        "name": "Sammy's",
        "sqlite_path": "data/sammys.db",
        "pg_database": "sammys_db",
    },
    {
        "name": "Tony's",
        "sqlite_path": "data/tonys.db",
        "pg_database": "tonys_db",
    },
    {
        "name": "Zucker's",
        "sqlite_path": "data/zuckers.db",
        "pg_database": "zuckers_db",
    },
]


def get_sqlite_engine(sqlite_path):
    """Create a SQLite engine."""
    return create_engine(f"sqlite:///./{sqlite_path}", echo=False)


def get_postgres_engine(database):
    """Create a PostgreSQL engine."""
    url = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{database}"
    return create_engine(url, echo=False)


def get_all_tables(engine):
    """Get all table names from an engine."""
    inspector = inspect(engine)
    return inspector.get_table_names()


def convert_sqlite_to_postgres_values(row_dict, target_engine, table_name):
    """Convert SQLite values to PostgreSQL-compatible values."""
    # Get column types from the target table
    inspector = inspect(target_engine)
    try:
        columns = {col['name']: col['type'] for col in inspector.get_columns(table_name)}
    except Exception:
        return row_dict

    converted = {}
    for key, value in row_dict.items():
        if key in columns:
            col_type = str(columns[key]).upper()
            # Convert SQLite integer booleans (0/1) to Python booleans for BOOLEAN columns
            if 'BOOLEAN' in col_type and isinstance(value, int):
                converted[key] = bool(value)
            else:
                converted[key] = value
        else:
            converted[key] = value
    return converted


def migrate_table(source_engine, target_engine, table_name):
    """Migrate a single table from source to target."""
    with source_engine.connect() as source_conn:
        # Get all rows from source
        result = source_conn.execute(text(f"SELECT * FROM {table_name}"))
        rows = result.fetchall()
        columns = result.keys()

        if not rows:
            print(f"    {table_name}: 0 rows (empty)")
            return 0

        # Build insert statement
        col_names = ", ".join(columns)
        placeholders = ", ".join([f":{col}" for col in columns])
        insert_sql = f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})"

        with target_engine.connect() as target_conn:
            # Insert rows in batches
            batch_size = 100
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                for row in batch:
                    row_dict = dict(zip(columns, row))
                    # Convert SQLite values to PostgreSQL-compatible values
                    row_dict = convert_sqlite_to_postgres_values(row_dict, target_engine, table_name)
                    try:
                        target_conn.execute(text(insert_sql), row_dict)
                    except Exception as e:
                        print(f"    Error inserting row in {table_name}: {e}")
                        print(f"    Row: {row_dict}")
                        raise
            target_conn.commit()

        print(f"    {table_name}: {len(rows)} rows migrated")
        return len(rows)


def reset_sequences(engine, table_name):
    """Reset PostgreSQL sequences after data import."""
    with engine.connect() as conn:
        # Get the max id from the table
        result = conn.execute(text(f"SELECT MAX(id) FROM {table_name}"))
        max_id = result.scalar() or 0

        # Reset the sequence
        seq_name = f"{table_name}_id_seq"
        try:
            conn.execute(text(f"SELECT setval('{seq_name}', {max_id + 1}, false)"))
            conn.commit()
        except Exception:
            # Sequence might not exist for some tables
            pass


def migrate_database(migration_config):
    """Migrate a single SQLite database to PostgreSQL."""
    name = migration_config["name"]
    sqlite_path = migration_config["sqlite_path"]
    pg_database = migration_config["pg_database"]

    print(f"\n{'='*60}")
    print(f"Migrating {name}")
    print(f"  Source: {sqlite_path}")
    print(f"  Target: {pg_database}")
    print(f"{'='*60}")

    # Check if SQLite file exists
    if not os.path.exists(sqlite_path):
        print(f"  ERROR: SQLite file not found: {sqlite_path}")
        return False

    # Create engines
    source_engine = get_sqlite_engine(sqlite_path)
    target_engine = get_postgres_engine(pg_database)

    # Drop and recreate all tables in PostgreSQL
    print("\n  Dropping existing tables in PostgreSQL...")
    Base.metadata.drop_all(target_engine)
    print("  Creating tables in PostgreSQL...")
    Base.metadata.create_all(target_engine)
    print("  Tables created.")

    # Get list of tables from SQLite
    source_tables = get_all_tables(source_engine)
    target_tables = get_all_tables(target_engine)

    print(f"\n  Found {len(source_tables)} tables in SQLite")
    print(f"  Found {len(target_tables)} tables in PostgreSQL")

    # Migrate tables in dependency order (tables with foreign keys should come after their parents)
    # Order matters for foreign key constraints
    table_order = [
        "company",
        "stores",
        "item_types",
        "attribute_definitions",
        "attribute_options",
        "ingredients",
        "attribute_option_ingredients",
        "ingredient_store_availability",
        "recipes",
        "recipe_ingredients",
        "recipe_choice_groups",
        "recipe_choice_items",
        "menu_items",
        "menu_item_store_availability",
        "orders",
        "order_items",
        "chat_sessions",
        "session_analytics",
    ]

    # Add any tables not in our predefined order
    for table in source_tables:
        if table not in table_order and table != "alembic_version":
            table_order.append(table)

    print("\n  Migrating data...")
    total_rows = 0

    for table_name in table_order:
        if table_name in source_tables and table_name in target_tables:
            try:
                rows = migrate_table(source_engine, target_engine, table_name)
                total_rows += rows
                reset_sequences(target_engine, table_name)
            except Exception as e:
                print(f"    ERROR migrating {table_name}: {e}")
                return False

    print(f"\n  Migration complete! Total rows: {total_rows}")
    return True


def main():
    print("=" * 60)
    print("SQLite to PostgreSQL Migration")
    print("=" * 60)

    # Install psycopg2 if needed
    try:
        import psycopg2
    except ImportError:
        print("Installing psycopg2-binary...")
        os.system("pip install psycopg2-binary")
        import psycopg2

    # Test PostgreSQL connection
    print("\nTesting PostgreSQL connection...")
    try:
        test_engine = get_postgres_engine("postgres")
        with test_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("PostgreSQL connection successful!")
    except Exception as e:
        print(f"ERROR: Could not connect to PostgreSQL: {e}")
        print("\nMake sure PostgreSQL is running:")
        print("  docker run -d --name postgres-orderbot \\")
        print("    -e POSTGRES_USER=orderbot \\")
        print("    -e POSTGRES_PASSWORD=orderbot123 \\")
        print("    -p 5432:5432 postgres:16")
        return 1

    # Run migrations
    success_count = 0
    for migration in MIGRATIONS:
        if migrate_database(migration):
            success_count += 1

    print("\n" + "=" * 60)
    print(f"Migration Summary: {success_count}/{len(MIGRATIONS)} databases migrated successfully")
    print("=" * 60)

    if success_count == len(MIGRATIONS):
        print("\nTo start the app with a PostgreSQL database, use:")
        print("  Sammy's:  DATABASE_URL=postgresql://orderbot:orderbot123@localhost:5432/sammys_db")
        print("  Tony's:   DATABASE_URL=postgresql://orderbot:orderbot123@localhost:5432/tonys_db")
        print("  Zucker's: DATABASE_URL=postgresql://orderbot:orderbot123@localhost:5432/zuckers_db")
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
