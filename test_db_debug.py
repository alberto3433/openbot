"""Debug database connectivity step by step."""
from dotenv import load_dotenv
load_dotenv()

import os
import socket
import time
from urllib.parse import urlparse

url = os.getenv('DATABASE_URL')
print(f"1. DATABASE_URL set: {bool(url)}")

if not url:
    print("ERROR: DATABASE_URL not found in .env")
    exit(1)

# Parse the URL
parsed = urlparse(url)
host = parsed.hostname
port = parsed.port or 5432

print(f"2. Host: {host}")
print(f"3. Port: {port}")

# Test DNS resolution
print(f"\n4. Testing DNS resolution...")
start = time.time()
try:
    ip = socket.gethostbyname(host)
    print(f"   SUCCESS: {host} -> {ip} ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"   FAILED: {e}")
    exit(1)

# Test TCP connection
print(f"\n5. Testing TCP connection to {ip}:{port}...")
start = time.time()
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(10)
try:
    sock.connect((ip, port))
    print(f"   SUCCESS: TCP connected ({time.time()-start:.2f}s)")
    sock.close()
except Exception as e:
    print(f"   FAILED after {time.time()-start:.2f}s: {e}")
    print("\n   >>> This is likely a FIREWALL issue blocking port 5432 <<<")
    exit(1)

# Test SQLAlchemy connection
print(f"\n6. Testing SQLAlchemy connection...")
start = time.time()
try:
    from sqlalchemy import create_engine, text
    engine = create_engine(url, connect_args={'connect_timeout': 10})
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
        print(f"   SUCCESS: Database query worked ({time.time()-start:.2f}s)")
except Exception as e:
    print(f"   FAILED after {time.time()-start:.2f}s: {e}")
