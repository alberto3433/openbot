"""Test imports step by step."""
import time

print("1. Importing dotenv...")
start = time.time()
from dotenv import load_dotenv
print(f"   Done ({time.time()-start:.2f}s)")

print("2. Loading .env...")
start = time.time()
load_dotenv()
print(f"   Done ({time.time()-start:.2f}s)")

print("3. Importing os...")
start = time.time()
import os
print(f"   Done ({time.time()-start:.2f}s)")

print("4. Importing sqlalchemy.create_engine...")
start = time.time()
from sqlalchemy import create_engine
print(f"   Done ({time.time()-start:.2f}s)")

print("5. Importing sqlalchemy.text...")
start = time.time()
from sqlalchemy import text
print(f"   Done ({time.time()-start:.2f}s)")

print("6. Importing NullPool...")
start = time.time()
from sqlalchemy.pool import NullPool
print(f"   Done ({time.time()-start:.2f}s)")

print("7. Getting DATABASE_URL...")
start = time.time()
url = os.getenv('DATABASE_URL')
print(f"   Done ({time.time()-start:.2f}s)")

print("8. Creating engine with NullPool...")
start = time.time()
engine = create_engine(url, poolclass=NullPool, connect_args={'connect_timeout': 10})
print(f"   Done ({time.time()-start:.2f}s)")

print("9. Connecting...")
start = time.time()
with engine.connect() as conn:
    result = conn.execute(text('SELECT 1'))
    print(f"   SUCCESS! ({time.time()-start:.2f}s)")
