"""Diagnose Python environment."""
import sys
print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")
print(f"sys.path:")
for p in sys.path:
    print(f"  {p}")
