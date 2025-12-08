import sqlite3

db_path = "app.db"
sql_path = "menu_items.sql"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

with open(sql_path, "r", encoding="utf-8") as f:
    sql_script = f.read()

cursor.executescript(sql_script)
conn.commit()
conn.close()

print("Database initialized successfully!")
