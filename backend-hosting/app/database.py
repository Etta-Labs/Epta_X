"""
Database module for ETTA-X application (PostgreSQL/Neon)
PostgreSQL database initialization and user management for hosted environments.

Uses Neon PostgreSQL for persistent storage in cloud deployments.
"""

import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool

# Database configuration - Neon PostgreSQL connection string
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_Mltb0WdHcu8E@ep-jolly-heart-aiebp7de-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require"
)

# Connection pool for efficient database access
_connection_pool = None


def get_connection_pool():
    """Get or create the connection pool."""
    global _connection_pool
    if _connection_pool is None:
        try:
            _connection_pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=DATABASE_URL
            )
            print("PostgreSQL connection pool created successfully")
        except Exception as e:
            print(f"Error creating connection pool: {e}")
            raise
    return _connection_pool


@contextmanager
def get_db_connection():
    """Context manager for database connections from pool."""
    db_pool = get_connection_pool()
    conn = None
    try:
        conn = db_pool.getconn()
        conn.autocommit = False
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            db_pool.putconn(conn)


def init_database():
    """Initialize the PostgreSQL database with required tables."""
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Users table - stores GitHub user information
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                github_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255),
                name VARCHAR(255),
                avatar_url TEXT,
                bio TEXT,
                location VARCHAR(255),
                company VARCHAR(255),
                blog VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                is_setup_complete BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # User settings table - stores user preferences
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                theme VARCHAR(50) DEFAULT 'dark',
                notifications_enabled BOOLEAN DEFAULT TRUE,
                default_branch VARCHAR(100) DEFAULT 'main',
                editor_font_size INTEGER DEFAULT 14,
                auto_save BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # User sessions table - stores active sessions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id SERIAL PRIMARY KEY,
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
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                github_repo_id BIGINT NOT NULL,
                name VARCHAR(255) NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                description TEXT,
                url TEXT,
                clone_url TEXT,
                default_branch VARCHAR(100) DEFAULT 'main',
                is_private BOOLEAN DEFAULT FALSE,
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
                id SERIAL PRIMARY KEY,
                repository_id INTEGER NOT NULL,
                github_hook_id BIGINT NOT NULL,
                webhook_url TEXT NOT NULL,
                secret_hash TEXT NOT NULL,
                events TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
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
                id SERIAL PRIMARY KEY,
                webhook_id INTEGER,
                github_delivery_id VARCHAR(255) UNIQUE,
                event_type VARCHAR(50) NOT NULL,
                repository_full_name VARCHAR(255) NOT NULL,
                branch VARCHAR(255),
                commit_sha VARCHAR(40),
                before_sha VARCHAR(40),
                payload TEXT NOT NULL,
                processed BOOLEAN DEFAULT FALSE,
                processed_at TIMESTAMP,
                processing_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (webhook_id) REFERENCES webhooks(id) ON DELETE SET NULL
            )
        """)
        
        # Create indexes for faster queries
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
            INSERT INTO app_metadata (key, value) 
            VALUES ('db_version', '1.0.0')
            ON CONFLICT (key) DO NOTHING
        """)
        cursor.execute("""
            INSERT INTO app_metadata (key, value) 
            VALUES ('setup_complete', 'false')
            ON CONFLICT (key) DO NOTHING
        """)
        
        conn.commit()
        
    print("PostgreSQL database initialized successfully")
    return True


def is_first_run() -> bool:
    """Check if this is the first run of the application."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT value FROM app_metadata WHERE key = 'setup_complete'")
            row = cursor.fetchone()
            if row is None:
                return True
            return row['value'] != 'true'
    except Exception:
        return True


def mark_setup_complete():
    """Mark the initial setup as complete."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO app_metadata (key, value, updated_at)
            VALUES ('setup_complete', 'true', CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET 
                value = 'true',
                updated_at = CURRENT_TIMESTAMP
        """)
        conn.commit()


# ==================== USER CRUD ====================

def create_user(github_data: dict) -> Optional[dict]:
    """Create or update a user from GitHub OAuth data."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                INSERT INTO users (
                    github_id, username, email, name, avatar_url,
                    bio, location, company, blog, is_setup_complete, last_login_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                ON CONFLICT (github_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    avatar_url = EXCLUDED.avatar_url,
                    bio = EXCLUDED.bio,
                    location = EXCLUDED.location,
                    company = EXCLUDED.company,
                    blog = EXCLUDED.blog,
                    last_login_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING *
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
            
            conn.commit()
            user = cursor.fetchone()
            
            # Also mark setup complete since user logged in
            mark_setup_complete()
            
            return dict(user) if user else None
            
        except Exception as e:
            print(f"Error creating user: {e}")
            conn.rollback()
            return None


def get_user_by_github_id(github_id: int) -> Optional[dict]:
    """Get a user by their GitHub ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE github_id = %s", (github_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    """Get a user by their database ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[dict]:
    """Get a user by their username."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_user(user_id: int, updates: dict) -> Optional[dict]:
    """Update user fields."""
    if not updates:
        return get_user_by_id(user_id)
    
    set_clauses = []
    values = []
    
    for key, value in updates.items():
        if key in ['email', 'name', 'avatar_url', 'bio', 'location', 'company', 'blog', 'is_active']:
            set_clauses.append(f"{key} = %s")
            values.append(value)
    
    if not set_clauses:
        return get_user_by_id(user_id)
    
    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    values.append(user_id)
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        query = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"
        cursor.execute(query, values)
        conn.commit()
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_users() -> list:
    """Get all users (admin function)."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id, github_id, username, name, email, avatar_url, 
                   is_active, created_at, last_login_at 
            FROM users
        """)
        return [dict(row) for row in cursor.fetchall()]


def user_exists() -> bool:
    """Check if any user exists in the database."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT COUNT(*) as count FROM users")
        row = cursor.fetchone()
        return row['count'] > 0 if row else False


# ==================== USER SETTINGS CRUD ====================

def get_user_settings(user_id: int) -> Optional[dict]:
    """Get settings for a user."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM user_settings WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        
        # Create default settings if none exist
        cursor.execute("""
            INSERT INTO user_settings (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
            RETURNING *
        """, (user_id,))
        conn.commit()
        row = cursor.fetchone()
        return dict(row) if row else None


def update_user_settings(user_id: int, settings: dict) -> Optional[dict]:
    """Update user settings."""
    set_clauses = []
    values = []
    
    for key, value in settings.items():
        if key in ['theme', 'notifications_enabled', 'default_branch', 'editor_font_size', 'auto_save']:
            set_clauses.append(f"{key} = %s")
            values.append(value)
    
    if not set_clauses:
        return get_user_settings(user_id)
    
    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    values.append(user_id)
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        query = f"UPDATE user_settings SET {', '.join(set_clauses)} WHERE user_id = %s RETURNING *"
        cursor.execute(query, values)
        conn.commit()
        row = cursor.fetchone()
        return dict(row) if row else None


# ==================== REPOSITORY CRUD ====================

def create_repository(user_id: int, repo_data: dict) -> Optional[dict]:
    """Create or update a repository record."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                INSERT INTO repositories (
                    user_id, github_repo_id, name, full_name, description,
                    url, clone_url, default_branch, is_private
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, github_repo_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    full_name = EXCLUDED.full_name,
                    description = EXCLUDED.description,
                    url = EXCLUDED.url,
                    clone_url = EXCLUDED.clone_url,
                    default_branch = EXCLUDED.default_branch,
                    is_private = EXCLUDED.is_private,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING *
            """, (
                user_id,
                repo_data.get('id'),
                repo_data.get('name'),
                repo_data.get('full_name'),
                repo_data.get('description'),
                repo_data.get('html_url'),
                repo_data.get('clone_url'),
                repo_data.get('default_branch', 'main'),
                repo_data.get('private', False),
            ))
            
            conn.commit()
            row = cursor.fetchone()
            return dict(row) if row else None
            
        except Exception as e:
            print(f"Error creating repository: {e}")
            conn.rollback()
            return None


def get_repository_by_github_id(user_id: int, github_repo_id: int) -> Optional[dict]:
    """Get a repository by GitHub repo ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM repositories WHERE user_id = %s AND github_repo_id = %s",
            (user_id, github_repo_id)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_repository_by_full_name(full_name: str) -> Optional[dict]:
    """Get a repository by full name (owner/repo)."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM repositories WHERE full_name = %s", (full_name,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_repositories(user_id: int) -> list:
    """Get all repositories for a user."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM repositories WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


# ==================== WEBHOOK CRUD ====================

def create_webhook(repository_id: int, github_hook_id: int, webhook_url: str, 
                   secret_hash: str, events: list) -> Optional[dict]:
    """Create a webhook record."""
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                INSERT INTO webhooks (
                    repository_id, github_hook_id, webhook_url, secret_hash, events
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (repository_id, github_hook_id) DO UPDATE SET
                    webhook_url = EXCLUDED.webhook_url,
                    secret_hash = EXCLUDED.secret_hash,
                    events = EXCLUDED.events,
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING *
            """, (
                repository_id,
                github_hook_id,
                webhook_url,
                secret_hash,
                json.dumps(events),
            ))
            
            conn.commit()
            row = cursor.fetchone()
            return dict(row) if row else None
            
        except Exception as e:
            print(f"Error creating webhook: {e}")
            conn.rollback()
            return None


def get_webhook_by_repository(repository_id: int) -> Optional[dict]:
    """Get webhook for a repository."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM webhooks WHERE repository_id = %s AND is_active = TRUE",
            (repository_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_webhook_secret_hash(repository_id: int) -> Optional[str]:
    """Get webhook secret hash for signature verification."""
    webhook = get_webhook_by_repository(repository_id)
    return webhook.get('secret_hash') if webhook else None


def update_webhook_delivery(webhook_id: int, status: str):
    """Update last delivery info for a webhook."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE webhooks 
            SET last_delivery_at = CURRENT_TIMESTAMP,
                last_delivery_status = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (status, webhook_id))
        conn.commit()


def deactivate_webhook(webhook_id: int):
    """Deactivate a webhook."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE webhooks 
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (webhook_id,))
        conn.commit()


# ==================== WEBHOOK EVENTS CRUD ====================

def create_webhook_event(
    webhook_id: Optional[int],
    delivery_id: str,
    event_type: str,
    repository_full_name: str,
    payload: dict,
    branch: Optional[str] = None,
    commit_sha: Optional[str] = None,
    before_sha: Optional[str] = None
) -> Optional[dict]:
    """Create a webhook event record."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                INSERT INTO webhook_events (
                    webhook_id, github_delivery_id, event_type, repository_full_name,
                    branch, commit_sha, before_sha, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (github_delivery_id) DO UPDATE SET
                    event_type = EXCLUDED.event_type,
                    repository_full_name = EXCLUDED.repository_full_name,
                    branch = EXCLUDED.branch,
                    commit_sha = EXCLUDED.commit_sha,
                    before_sha = EXCLUDED.before_sha,
                    payload = EXCLUDED.payload
                RETURNING *
            """, (
                webhook_id,
                delivery_id,
                event_type,
                repository_full_name,
                branch,
                commit_sha,
                before_sha,
                json.dumps(payload) if isinstance(payload, dict) else payload,
            ))
            
            conn.commit()
            row = cursor.fetchone()
            return dict(row) if row else None
            
        except Exception as e:
            print(f"Error creating webhook event: {e}")
            conn.rollback()
            return None


def get_webhook_event_by_delivery_id(delivery_id: str) -> Optional[dict]:
    """Get a webhook event by its delivery ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM webhook_events WHERE github_delivery_id = %s",
            (delivery_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_unprocessed_webhook_events(limit: int = 100) -> list:
    """Get unprocessed webhook events for background processing."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT * FROM webhook_events 
            WHERE processed = FALSE 
            ORDER BY created_at ASC 
            LIMIT %s
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def mark_webhook_event_processed(event_id: int, result: Optional[str] = None):
    """Mark a webhook event as processed."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE webhook_events 
            SET processed = TRUE,
                processed_at = CURRENT_TIMESTAMP,
                processing_result = %s
            WHERE id = %s
        """, (result, event_id))
        conn.commit()


def get_recent_webhook_events(repository_full_name: str = None, limit: int = 10) -> list:
    """Get recent webhook events, optionally filtered by repository."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if repository_full_name is None:
            cursor.execute("""
                SELECT * FROM webhook_events 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (limit,))
        else:
            cursor.execute("""
                SELECT * FROM webhook_events 
                WHERE repository_full_name = %s 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (repository_full_name, limit))
        return [dict(row) for row in cursor.fetchall()]


def get_webhook_event_by_id(event_id: int) -> Optional[dict]:
    """Get a webhook event by its database ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM webhook_events WHERE id = %s", (event_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
