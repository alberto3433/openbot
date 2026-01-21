"""Find where SQLAlchemy is installed."""
import sys
print(f"Python: {sys.executable}")
print(f"Version: {sys.version}")

# Try to find sqlalchemy without importing it
import importlib.util
spec = importlib.util.find_spec("sqlalchemy")
if spec:
    print(f"SQLAlchemy found at: {spec.origin}")
else:
    print("SQLAlchemy NOT FOUND")
