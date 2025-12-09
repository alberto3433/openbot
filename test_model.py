from pathlib import Path
import os
from dotenv import load_dotenv
from openai import OpenAI

env_path = Path(".").resolve() / ".env"
print("env_path:", env_path, "exists:", env_path.exists())

load_dotenv(env_path)

key = os.getenv("OPENAI_API_KEY")
print("Loaded OPENAI_API_KEY prefix:", (key or "")[:12])

if not key:
    print("No key loaded from .env")
    raise SystemExit(1)

client = OpenAI(api_key=key)

try:
    models = client.models.list()
    print("✅ Models call succeeded. First model id:", models.data[0].id if models.data else "no models")
except Exception as e:
    print("❌ Error calling OpenAI:", repr(e))
