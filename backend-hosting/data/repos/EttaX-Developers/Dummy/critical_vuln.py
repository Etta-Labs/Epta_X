# CRITICAL SECURITY VULNERABILITY - SQL INJECTION
import sqlite3

def get_user_unsafe(user_id):
    """SQL Injection vulnerability - user input directly in query"""
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE id = {user_id}"  # DANGEROUS!
    return conn.execute(query).fetchone()

def delete_account_unsafe(username, password):
    """No authentication check before deletion"""
    conn = sqlite3.connect("users.db")
    # CRITICAL: No password verification
    conn.execute(f"DELETE FROM users WHERE username = '{username}'")
    conn.commit()
    return {"deleted": username}

def transfer_funds_unsafe(from_user, to_user, amount):
    """Race condition vulnerability - no transaction locking"""
    conn = sqlite3.connect("bank.db")
    # DANGER: No atomic transaction
    balance = conn.execute(f"SELECT balance FROM accounts WHERE user='{from_user}'").fetchone()[0]
    if balance >= amount:
        conn.execute(f"UPDATE accounts SET balance = balance - {amount} WHERE user='{from_user}'")
        conn.execute(f"UPDATE accounts SET balance = balance + {amount} WHERE user='{to_user}'")
    return {"transferred": amount}
