import sqlite3

c = sqlite3.connect('steeplechase.db')
try:
    # 1. Update LabelFlags
    c.execute("ALTER TABLE label_flags ADD COLUMN status VARCHAR(10) DEFAULT 'pending'")
    c.execute("ALTER TABLE label_flags ADD COLUMN session_id INTEGER")
    c.execute("ALTER TABLE label_flags ADD COLUMN student_answer TEXT DEFAULT ''")
    c.execute("ALTER TABLE label_flags ADD COLUMN resolved_at DATETIME")
    c.execute("ALTER TABLE label_flags ADD COLUMN resolved_by INTEGER")
    
    # 2. Update LabelRegions (for spellcheck audit)
    c.execute("ALTER TABLE label_regions ADD COLUMN corrected_from VARCHAR(300)")
    
    # 3. Update LabelAudits
    c.execute("ALTER TABLE label_audits ADD COLUMN action VARCHAR(20) DEFAULT 'decided'")
    c.execute("ALTER TABLE label_audits ADD COLUMN undone BOOLEAN DEFAULT 0")
    
    c.commit()
    print("Database updated for Stage 6b!")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("Columns already exist. You are good to go!")
    else:
        print(f"Error: {e}")