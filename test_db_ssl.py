"""Test PostgreSQL connection with psycopg2 directly."""
from dotenv import load_dotenv
load_dotenv()

import os
import time

url = os.getenv('DATABASE_URL')

print("Testing with psycopg2 directly...")
print("=" * 50)

# Parse connection params
from urllib.parse import urlparse, parse_qs
parsed = urlparse(url)

params = {
    'host': parsed.hostname,
    'port': parsed.port or 5432,
    'user': parsed.username,
    'password': parsed.password,
    'dbname': parsed.path[1:],  # Remove leading /
    'connect_timeout': 10,
}

# Get sslmode from query string
query = parse_qs(parsed.query)
if 'sslmode' in query:
    params['sslmode'] = query['sslmode'][0]

print(f"Host: {params['host']}")
print(f"Port: {params['port']}")
print(f"User: {params['user']}")
print(f"Database: {params['dbname']}")
print(f"SSL Mode: {params.get('sslmode', 'default')}")
print()

import psycopg2

# Test 1: With SSL (as configured)
print("Test 1: Connecting with sslmode=require...")
start = time.time()
try:
    conn = psycopg2.connect(**params)
    cur = conn.cursor()
    cur.execute('SELECT 1')
    print(f"   SUCCESS! ({time.time()-start:.2f}s)")
    conn.close()
except Exception as e:
    print(f"   FAILED after {time.time()-start:.2f}s")
    print(f"   Error: {e}")

# Test 2: Without SSL
print("\nTest 2: Connecting with sslmode=disable...")
params['sslmode'] = 'disable'
start = time.time()
try:
    conn = psycopg2.connect(**params)
    cur = conn.cursor()
    cur.execute('SELECT 1')
    print(f"   SUCCESS! ({time.time()-start:.2f}s)")
    conn.close()
except Exception as e:
    print(f"   FAILED after {time.time()-start:.2f}s")
    print(f"   Error: {e}")
