"""Test database connectivity."""
from dotenv import load_dotenv
load_dotenv()

import os
import time
from sqlalchemy import create_engine, text

url = os.getenv('DATABASE_URL')
print(f'DATABASE_URL set: {bool(url)}')
print('Connecting...')
start = time.time()

try:
    engine = create_engine(url, connect_args={'connect_timeout': 10})
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
        print(f'SUCCESS! Took {time.time()-start:.2f}s')
except Exception as e:
    print(f'FAILED after {time.time()-start:.2f}s')
    print(f'Error: {e}')
