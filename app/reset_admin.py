"""Emergency admin password reset — run on the server when completely locked out.

Usage:
    python3 -m app.reset_admin

Works with both SQLite and MongoDB backends (reads the same env vars as the app).
"""

import getpass
import hashlib
import os
import secrets
import sys
from pathlib import Path


def _hash(pw: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 260_000)
    return f"pbkdf2:{salt.hex()}:{digest.hex()}"


def _reset_sqlite(db_path: str, email: str, name: str, pw_hash: str) -> None:
    import sqlite3
    con = sqlite3.connect(db_path)
    existing = con.execute("SELECT email FROM admin_users WHERE email = ?", (email,)).fetchone()
    if existing:
        con.execute("UPDATE admin_users SET name = ?, password_hash = ? WHERE email = ?",
                    (name, pw_hash, email))
        print(f"Updated existing admin: {email}")
    else:
        con.execute("DELETE FROM admin_users")
        con.execute("INSERT INTO admin_users (email, name, password_hash) VALUES (?,?,?)",
                    (email, name, pw_hash))
        print(f"Replaced all admins with: {email}")
    con.commit()
    con.close()


def _reset_mongo(uri: str, db_name: str, email: str, name: str, pw_hash: str) -> None:
    from pymongo import MongoClient
    col = MongoClient(uri)[db_name]["admin_users"]
    existing = col.find_one({"email": email})
    if existing:
        col.update_one({"email": email}, {"$set": {"name": name, "password_hash": pw_hash}})
        print(f"Updated existing admin: {email}")
    else:
        col.delete_many({})
        col.insert_one({"email": email, "name": name, "password_hash": pw_hash, "created_at": ""})
        print(f"Replaced all admins with: {email}")


def main() -> None:
    print("=== APS ESAF Fetcher — Emergency Admin Reset ===\n")

    email = input("Admin email: ").strip().lower()
    name  = input("Admin name: ").strip()
    if not email or not name:
        print("Email and name are required.", file=sys.stderr)
        sys.exit(1)

    pw = getpass.getpass("New password (min 8 chars): ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw != pw2:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(1)
    if len(pw) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    pw_hash = _hash(pw)

    mongo_uri = os.getenv("MONGODB_URI", "")
    if mongo_uri:
        db_name = os.getenv("MONGODB_ESAF_DB", "aps_esaf")
        print(f"\nUsing MongoDB backend ({db_name})")
        _reset_mongo(mongo_uri, db_name, email, name, pw_hash)
    else:
        db_path = os.getenv("DB_PATH", str(Path.home() / ".aps-esaf-fetcher" / "esaf.db"))
        print(f"\nUsing SQLite backend ({db_path})")
        _reset_sqlite(db_path, email, name, pw_hash)

    print(f"\nDone. Log in at /admin/login with:  {email}")


if __name__ == "__main__":
    main()
