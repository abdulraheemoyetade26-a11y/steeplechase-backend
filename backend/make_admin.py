import sqlite3
email = input("Enter your admin email: ")
c = sqlite3.connect('steeplechase.db')
c.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
c.commit()
print(f"{email} is now an admin.")