"""
migrate_db.py — SECEL Database Migration
Run this ONCE to add new columns to the existing SQLite database.
Usage: python migrate_db.py
"""
import os, sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'secel.db')

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"[!] Database not found at {DB_PATH}")
        print("    Start the app once with db.create_all() to create it, then run this script.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # New columns for the 'courses' table
    new_columns = [
        ('course_type',          "VARCHAR(20)  DEFAULT 'video'"),
        ('is_approved',          "BOOLEAN      DEFAULT 0"),
        ('approval_status',      "VARCHAR(20)  DEFAULT 'pending'"),
        ('rejection_reason',     "TEXT"),
        ('ebook_cover',          "VARCHAR(255)"),
        ('ebook_file',           "VARCHAR(500)"),
        ('youtube_playlist_url', "VARCHAR(500)"),
    ]

    print(f"[*] Migrating database: {DB_PATH}\n")
    for col, dtype in new_columns:
        try:
            cur.execute(f"ALTER TABLE courses ADD COLUMN {col} {dtype}")
            print(f"  [+] Added column: courses.{col}")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e).lower():
                print(f"  [~] Already exists: courses.{col} — skipped")
            else:
                print(f"  [!] Error on {col}: {e}")

    conn.commit()
    conn.close()
    print("\n[OK] Migration complete.")

if __name__ == '__main__':
    migrate()
