"""Test SQLAlchemy with different configurations."""
from dotenv import load_dotenv
load_dotenv()

import os
import time

url = os.getenv('DATABASE_URL')

print("Testing SQLAlchemy configurations...")
print("=" * 50)

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# Test 1: Default SQLAlchemy
print("\nTest 1: Default SQLAlchemy (may hang)...")
print("   Skipping - we know this hangs")

# Test 2: With NullPool (no connection pooling)
print("\nTest 2: SQLAlchemy with NullPool...")
start = time.time()
try:
    engine = create_engine(
        url,
        poolclass=NullPool,
        connect_args={'connect_timeout': 10}
    )
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
        print(f"   SUCCESS! ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"   FAILED after {time.time()-start:.2f}s")
    print(f"   Error: {e}")

# Test 3: With explicit psycopg2 driver
print("\nTest 3: SQLAlchemy with postgresql+psycopg2://...")
url_psycopg2 = url.replace('postgresql://', 'postgresql+psycopg2://')
start = time.time()
try:
    engine = create_engine(
        url_psycopg2,
        poolclass=NullPool,
        connect_args={'connect_timeout': 10}
    )
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
        print(f"   SUCCESS! ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"   FAILED after {time.time()-start:.2f}s")
    print(f"   Error: {e}")

# Test 4: Check what driver SQLAlchemy uses by default
print("\nTest 4: Checking default SQLAlchemy driver...")
try:
    engine = create_engine(url)
    print(f"   Driver: {engine.driver}")
    print(f"   Dialect: {engine.dialect.name}")
except Exception as e:
    print(f"   Error: {e}")
