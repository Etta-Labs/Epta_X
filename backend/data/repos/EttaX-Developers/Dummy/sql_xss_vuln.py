# CRITICAL: SQL Injection and XSS vulnerabilities
import sqlite3

def search_users(query):
    """CRITICAL: SQL Injection vulnerability"""
    conn = sqlite3.connect('users.db')
    # Direct string interpolation - SQL INJECTION!
    result = conn.execute(f"SELECT * FROM users WHERE name LIKE '%{query}%'")
    return result.fetchall()

def render_comment(user_input):
    """CRITICAL: XSS vulnerability - unsanitized output"""
    # No HTML escaping - XSS ATTACK!
    return f"<div class='comment'>{user_input}</div>"

def process_file_upload(filename, content):
    """CRITICAL: Path traversal vulnerability"""
    # No path validation - PATH TRAVERSAL!
    with open(f"/uploads/{filename}", "wb") as f:
        f.write(content)
    return {"saved": filename}
