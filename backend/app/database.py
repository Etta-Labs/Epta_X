"""
Database module for ETTA-X application
SQLite database initialization and user management
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

# Database configuration
DB_PATH = os.getenv("DATABASE_PATH", "backend/data/etta_x.db")


def ensure_db_directory():
    """Ensure the database directory exists"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)


@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    ensure_db_directory()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode to prevent database locks
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """Initialize the SQLite database with required tables"""
    ensure_db_directory()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Users table - stores GitHub user information
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                github_id INTEGER UNIQUE NOT NULL,
                username VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255),
                name VARCHAR(255),
                avatar_url TEXT,
                bio TEXT,
                location VARCHAR(255),
                company VARCHAR(255),
                blog VARCHAR(255),
                is_active BOOLEAN DEFAULT 1,
                is_setup_complete BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # User settings table - stores user preferences
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                theme VARCHAR(50) DEFAULT 'dark',
                notifications_enabled BOOLEAN DEFAULT 1,
                default_branch VARCHAR(100) DEFAULT 'main',
                editor_font_size INTEGER DEFAULT 14,
                auto_save BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # User sessions table - stores active sessions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_token VARCHAR(255) UNIQUE NOT NULL,
                github_access_token TEXT NOT NULL,
                ip_address VARCHAR(45),
                user_agent TEXT,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Repositories table - stores linked GitHub repositories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS repositories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                github_repo_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                description TEXT,
                url TEXT,
                clone_url TEXT,
                default_branch VARCHAR(100) DEFAULT 'main',
                is_private BOOLEAN DEFAULT 0,
                last_synced_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, github_repo_id)
            )
        """)
        
        # App metadata table - stores application state
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_metadata (
                key VARCHAR(255) PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        
        # Set initial app metadata
        cursor.execute("""
            INSERT OR IGNORE INTO app_metadata (key, value) 
            VALUES ('db_version', '1.0.0')
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO app_metadata (key, value) 
            VALUES ('setup_complete', 'false')
        """)
        
        conn.commit()
        
    return True


def is_first_run() -> bool:
    """Check if this is the first run of the application"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_metadata WHERE key = 'setup_complete'")
            row = cursor.fetchone()
            return row is None or row['value'] != 'true'
    except sqlite3.OperationalError:
        return True


def mark_setup_complete():
    """Mark the initial setup as complete"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO app_metadata (key, value, updated_at) 
            VALUES ('setup_complete', 'true', CURRENT_TIMESTAMP)
        """)
        conn.commit()


# User CRUD operations
def create_user(github_data: dict) -> Optional[dict]:
    """Create a new user from GitHub data"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO users (
                    github_id, username, email, name, avatar_url, 
                    bio, location, company, blog, is_setup_complete
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                github_data.get('id'),
                github_data.get('login'),
                github_data.get('email'),
                github_data.get('name'),
                github_data.get('avatar_url'),
                github_data.get('bio'),
                github_data.get('location'),
                github_data.get('company'),
                github_data.get('blog'),
            ))
            
            user_id = cursor.lastrowid
            
            # Create default user settings
            cursor.execute("""
                INSERT INTO user_settings (user_id) VALUES (?)
            """, (user_id,))
            
            conn.commit()
            
            return get_user_by_github_id(github_data.get('id'))
            
        except sqlite3.IntegrityError:
            # User already exists, update instead
            return update_user(github_data)


def get_user_by_github_id(github_id: int) -> Optional[dict]:
    """Get a user by their GitHub ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE github_id = ?", (github_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[dict]:
    """Get a user by their username"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_user(github_data: dict) -> Optional[dict]:
    """Update an existing user with fresh GitHub data"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users SET
                username = ?,
                email = ?,
                name = ?,
                avatar_url = ?,
                bio = ?,
                location = ?,
                company = ?,
                blog = ?,
                updated_at = CURRENT_TIMESTAMP,
                last_login_at = CURRENT_TIMESTAMP
            WHERE github_id = ?
        """, (
            github_data.get('login'),
            github_data.get('email'),
            github_data.get('name'),
            github_data.get('avatar_url'),
            github_data.get('bio'),
            github_data.get('location'),
            github_data.get('company'),
            github_data.get('blog'),
            github_data.get('id'),
        ))
        
        conn.commit()
        
        return get_user_by_github_id(github_data.get('id'))


def get_user_settings(user_id: int) -> Optional[dict]:
    """Get user settings"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_user_settings(user_id: int, settings: dict) -> bool:
    """Update user settings"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Build dynamic update query
        allowed_fields = ['theme', 'notifications_enabled', 'default_branch', 
                          'editor_font_size', 'auto_save']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in settings:
                updates.append(f"{field} = ?")
                values.append(settings[field])
        
        if not updates:
            return False
        
        values.append(user_id)
        query = f"UPDATE user_settings SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?"
        
        cursor.execute(query, values)
        conn.commit()
        
        return cursor.rowcount > 0


def get_all_users() -> list:
    """Get all users (admin function)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, github_id, username, name, email, avatar_url, is_active, created_at, last_login_at FROM users")
        return [dict(row) for row in cursor.fetchall()]


def user_exists() -> bool:
    """Check if any user exists in the database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users")
        row = cursor.fetchone()
        return row['count'] > 0 if row else False


# Initialize database on module import
init_database()
