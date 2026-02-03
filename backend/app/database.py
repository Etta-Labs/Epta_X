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
    conn = sqlite3.connect(DB_PATH, timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency and prevent database locks
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=60000')
    conn.execute('PRAGMA synchronous=NORMAL')
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
        
        # Webhooks table - stores registered webhook configurations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_id INTEGER NOT NULL,
                github_hook_id INTEGER NOT NULL,
                webhook_url TEXT NOT NULL,
                secret_hash TEXT NOT NULL,
                events TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                last_delivery_at TIMESTAMP,
                last_delivery_status VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
                UNIQUE(repository_id, github_hook_id)
            )
        """)
        
        # Webhook events table - stores received webhook events for processing
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                webhook_id INTEGER,
                github_delivery_id VARCHAR(255) UNIQUE,
                event_type VARCHAR(50) NOT NULL,
                repository_full_name VARCHAR(255) NOT NULL,
                branch VARCHAR(255),
                commit_sha VARCHAR(40),
                before_sha VARCHAR(40),
                payload TEXT NOT NULL,
                processed BOOLEAN DEFAULT 0,
                processed_at TIMESTAMP,
                processing_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (webhook_id) REFERENCES webhooks(id) ON DELETE SET NULL
            )
        """)
        
        # Create index for faster webhook event queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_webhook_events_processed 
            ON webhook_events(processed, created_at)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_webhook_events_repo 
            ON webhook_events(repository_full_name, branch)
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
    """Create a new user from GitHub data, or update if exists"""
    github_id = github_data.get('id')
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # First check if user already exists
        cursor.execute("SELECT id FROM users WHERE github_id = ?", (github_id,))
        existing = cursor.fetchone()
        
        if existing:
            # User exists, update instead
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
                    is_setup_complete = 1,
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
                github_id,
            ))
            conn.commit()
        else:
            # Create new user
            cursor.execute("""
                INSERT INTO users (
                    github_id, username, email, name, avatar_url, 
                    bio, location, company, blog, is_setup_complete
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                github_id,
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
                INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)
            """, (user_id,))
            
            conn.commit()
        
        # Return the user data
        cursor.execute("SELECT * FROM users WHERE github_id = ?", (github_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


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


# ==================== REPOSITORY CRUD ====================

def create_repository(user_id: int, repo_data: dict) -> Optional[dict]:
    """Create or update a repository record"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO repositories (
                    user_id, github_repo_id, name, full_name, description,
                    url, clone_url, default_branch, is_private
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, github_repo_id) DO UPDATE SET
                    name = excluded.name,
                    full_name = excluded.full_name,
                    description = excluded.description,
                    url = excluded.url,
                    clone_url = excluded.clone_url,
                    default_branch = excluded.default_branch,
                    is_private = excluded.is_private,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                user_id,
                repo_data.get('id'),
                repo_data.get('name'),
                repo_data.get('full_name'),
                repo_data.get('description'),
                repo_data.get('html_url'),
                repo_data.get('clone_url'),
                repo_data.get('default_branch', 'main'),
                1 if repo_data.get('private') else 0,
            ))
            
            conn.commit()
            
            return get_repository_by_github_id(user_id, repo_data.get('id'))
            
        except Exception as e:
            print(f"Error creating repository: {e}")
            return None


def get_repository_by_github_id(user_id: int, github_repo_id: int) -> Optional[dict]:
    """Get a repository by GitHub repo ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM repositories WHERE user_id = ? AND github_repo_id = ?",
            (user_id, github_repo_id)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_repository_by_full_name(full_name: str) -> Optional[dict]:
    """Get a repository by full name (owner/repo)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM repositories WHERE full_name = ?", (full_name,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_repositories(user_id: int) -> list:
    """Get all repositories for a user"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM repositories WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


# ==================== WEBHOOK CRUD ====================

def create_webhook(repository_id: int, github_hook_id: int, webhook_url: str, 
                   secret_hash: str, events: list) -> Optional[dict]:
    """Create a webhook record"""
    import json
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO webhooks (
                    repository_id, github_hook_id, webhook_url, secret_hash, events
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, github_hook_id) DO UPDATE SET
                    webhook_url = excluded.webhook_url,
                    secret_hash = excluded.secret_hash,
                    events = excluded.events,
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                repository_id,
                github_hook_id,
                webhook_url,
                secret_hash,
                json.dumps(events),
            ))
            
            conn.commit()
            
            return get_webhook_by_github_id(repository_id, github_hook_id)
            
        except Exception as e:
            print(f"Error creating webhook: {e}")
            return None


def get_webhook_by_github_id(repository_id: int, github_hook_id: int) -> Optional[dict]:
    """Get a webhook by GitHub hook ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM webhooks WHERE repository_id = ? AND github_hook_id = ?",
            (repository_id, github_hook_id)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_webhook_by_repository(repository_id: int) -> Optional[dict]:
    """Get the active webhook for a repository"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM webhooks WHERE repository_id = ? AND is_active = 1",
            (repository_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_webhook_secret_hash(repository_full_name: str) -> Optional[str]:
    """Get the webhook secret hash for a repository (for signature verification)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT w.secret_hash 
            FROM webhooks w
            JOIN repositories r ON w.repository_id = r.id
            WHERE r.full_name = ? AND w.is_active = 1
        """, (repository_full_name,))
        row = cursor.fetchone()
        return row['secret_hash'] if row else None


def update_webhook_delivery(repository_id: int, github_hook_id: int, 
                            status: str) -> bool:
    """Update webhook last delivery info"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE webhooks 
            SET last_delivery_at = CURRENT_TIMESTAMP,
                last_delivery_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE repository_id = ? AND github_hook_id = ?
        """, (status, repository_id, github_hook_id))
        conn.commit()
        return cursor.rowcount > 0


def deactivate_webhook(repository_id: int, github_hook_id: int) -> bool:
    """Mark a webhook as inactive"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE webhooks 
            SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE repository_id = ? AND github_hook_id = ?
        """, (repository_id, github_hook_id))
        conn.commit()
        return cursor.rowcount > 0


# ==================== WEBHOOK EVENT CRUD ====================

def create_webhook_event(event_data: dict) -> Optional[dict]:
    """Create a webhook event record for processing"""
    import json
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO webhook_events (
                    webhook_id, github_delivery_id, event_type,
                    repository_full_name, branch, commit_sha, before_sha, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_data.get('webhook_id'),
                event_data.get('delivery_id'),
                event_data.get('event_type'),
                event_data.get('repository_full_name'),
                event_data.get('branch'),
                event_data.get('commit_sha'),
                event_data.get('before_sha'),
                json.dumps(event_data.get('payload', {})),
            ))
            
            conn.commit()
            
            return get_webhook_event_by_id(cursor.lastrowid)
            
        except Exception as e:
            print(f"Error creating webhook event: {e}")
            return None


def get_webhook_event_by_id(event_id: int) -> Optional[dict]:
    """Get a webhook event by ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM webhook_events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_webhook_event_by_delivery_id(delivery_id: str) -> Optional[dict]:
    """Get a webhook event by GitHub delivery ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM webhook_events WHERE github_delivery_id = ?",
            (delivery_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_unprocessed_webhook_events(limit: int = 100) -> list:
    """Get unprocessed webhook events for processing"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM webhook_events 
            WHERE processed = 0 
            ORDER BY created_at ASC 
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def mark_webhook_event_processed(event_id: int, result: str = None) -> bool:
    """Mark a webhook event as processed"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE webhook_events 
            SET processed = 1,
                processed_at = CURRENT_TIMESTAMP,
                processing_result = ?
            WHERE id = ?
        """, (result, event_id))
        conn.commit()
        return cursor.rowcount > 0


def get_recent_webhook_events(repository_full_name: str = None, 
                               limit: int = 50) -> list:
    """Get recent webhook events, optionally filtered by repository"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if repository_full_name:
            cursor.execute("""
                SELECT * FROM webhook_events 
                WHERE repository_full_name = ?
                ORDER BY created_at DESC 
                LIMIT ?
            """, (repository_full_name, limit))
        else:
            cursor.execute("""
                SELECT * FROM webhook_events 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]

# Database is initialized via app.py startup event