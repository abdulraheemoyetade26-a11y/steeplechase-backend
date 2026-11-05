import sqlite3

c = sqlite3.connect('steeplechase.db')
try:
    c.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
    c.execute("ALTER TABLE users ADD COLUMN last_active_at DATETIME")
    c.commit()
    print("Database updated for Stage 6d!")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("Columns already exist. You are good to go!")
    else:
        print(f"Error: {e}")