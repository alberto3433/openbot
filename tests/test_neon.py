import psycopg2

# Your Neon connection string
DATABASE_URL = "postgresql://neondb_owner:npg_Ts70LESCvPJe@ep-proud-dew-ah2ksvl2-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require"

try:
    print("Attempting connection...")
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    print("✓ Connected successfully!")

    cur = conn.cursor()
    cur.execute("SELECT version();")
    print(f"✓ PostgreSQL version: {cur.fetchone()[0][:50]}...")

    conn.close()
    print("✓ Connection closed cleanly")
except Exception as e:
    print(f"✗ Failed: {type(e).__name__}: {e}")
