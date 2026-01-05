"""Temporary script to query menu items for disambiguation analysis."""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'app.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Query coffee-related items causing disambiguation
print("=" * 80)
print("COFFEE ITEMS CAUSING DISAMBIGUATION")
print("=" * 80)
cursor.execute("""
SELECT id, name, category, base_price
FROM menu_items
WHERE LOWER(name) LIKE '%latte%'
   OR LOWER(name) LIKE '%cappuccino%'
   OR LOWER(name) LIKE '%espresso%'
ORDER BY category, name
""")
print(f"{'ID':<5} {'Name':<45} {'Category':<15} {'Price':<10}")
print("-" * 80)
for row in cursor.fetchall():
    print(f"{row[0]:<5} {row[1]:<45} {row[2]:<15} ${row[3]:<10.2f}")

# Query juice items
print("\n" + "=" * 80)
print("JUICE ITEMS")
print("=" * 80)
cursor.execute("""
SELECT id, name, category, base_price
FROM menu_items
WHERE LOWER(name) LIKE '%juice%'
ORDER BY category, name
""")
print(f"{'ID':<5} {'Name':<45} {'Category':<15} {'Price':<10}")
print("-" * 80)
for row in cursor.fetchall():
    print(f"{row[0]:<5} {row[1]:<45} {row[2]:<15} ${row[3]:<10.2f}")

conn.close()
