import sqlite3

c = sqlite3.connect('steeplechase.db')
try:
    # Update Users table
    c.execute("ALTER TABLE users ADD COLUMN usage_month VARCHAR(10) DEFAULT ''")
    c.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone ON users(phone)")
    
    # Create ActivationCode table
    c.execute('''
        CREATE TABLE IF NOT EXISTS activation_codes (
            id INTEGER PRIMARY KEY,
            code VARCHAR(16) UNIQUE,
            plan VARCHAR(10),
            days INTEGER DEFAULT 30,
            batch VARCHAR(40) DEFAULT '',
            created_at DATETIME,
            used_by INTEGER,
            used_at DATETIME,
            FOREIGN KEY(used_by) REFERENCES users(id)
        )
    ''')
    c.commit()
    print("Database updated for Stage 6c!")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("Columns already exist. You are good to go!")
    else:
        print(f"Error: {e}")