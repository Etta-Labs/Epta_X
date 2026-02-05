# SQL Injection Vulnerability
import sqlite3

def get_user_unsafe(user_id):
    """CRITICAL: SQL injection vulnerable"""
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE id = {user_id}"  # Unsafe!
    return conn.execute(query).fetchone()

def login_unsafe(username, password):
    """CRITICAL: SQL injection in login"""
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    return conn.execute(query).fetchone()
