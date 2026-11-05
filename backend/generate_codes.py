import random
import sqlite3
from datetime import datetime

c = sqlite3.connect('steeplechase.db')

def generate_code():
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part1 = "".join(random.choice(chars) for _ in range(4))
    part2 = "".join(random.choice(chars) for _ in range(4))
    return f"STP-{part1}-{part2}"

def create_codes(plan, days, count, batch_name):
    now = datetime.now().isoformat()
    for _ in range(count):
        code = generate_code()
        try:
            c.execute(
                "INSERT INTO activation_codes (code, plan, days, batch, created_at) VALUES (?, ?, ?, ?, ?)",
                (code, plan, days, batch_name, now)
            )
        except sqlite3.IntegrityError:
            return create_codes(plan, days, count, batch_name)
    c.commit()

create_codes("pro", 30, 15, "beta-pro")
print("15 Pro codes generated!")

create_codes("basic", 30, 35, "beta-basic")
print("35 Basic codes generated!")

print("\n--- YOUR 50 BETA CODES ---")
rows = c.execute("SELECT code, plan FROM activation_codes WHERE batch IN ('beta-pro', 'beta-basic')").fetchall()
for code, plan in rows:
    print(f"[{plan.upper()}] {code}")