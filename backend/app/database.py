"""
Database module for ETTA-X application
SQLite database initialization and user management
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

# Database configuration
DB_PATH = os.getenv("DATABASE_PATH", "backend/data/etta_x.db")

# Default clone path configuration
DEFAULT_CLONE_PATH = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "etta-x", "repos")


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
        
        # =========================================
        # PHASE 1: Repository Intelligence Tables
        # =========================================
        
        # Cloned repositories table - tracks locally cloned repos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cloned_repositories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                repository_id INTEGER,
                github_repo_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                owner VARCHAR(255) NOT NULL,
                local_path TEXT NOT NULL,
                clone_url TEXT NOT NULL,
                current_branch VARCHAR(100) DEFAULT 'main',
                last_commit_sha VARCHAR(40),
                clone_status VARCHAR(50) DEFAULT 'pending',
                clone_progress INTEGER DEFAULT 0,
                error_message TEXT,
                cloned_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE SET NULL
            )
        """)
        
        # Commit snapshots table - stores commit metadata and diff summaries
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commit_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cloned_repo_id INTEGER NOT NULL,
                commit_sha VARCHAR(40) NOT NULL,
                parent_sha VARCHAR(40),
                commit_message TEXT,
                author_name VARCHAR(255),
                author_email VARCHAR(255),
                committed_at TIMESTAMP,
                total_files_changed INTEGER DEFAULT 0,
                total_lines_added INTEGER DEFAULT 0,
                total_lines_removed INTEGER DEFAULT 0,
                diff_computed BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cloned_repo_id) REFERENCES cloned_repositories(id) ON DELETE CASCADE,
                UNIQUE(cloned_repo_id, commit_sha)
            )
        """)
        
        # File changes table - stores per-file diff information
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_snapshot_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                change_type VARCHAR(20) NOT NULL,
                language VARCHAR(50),
                lines_added INTEGER DEFAULT 0,
                lines_removed INTEGER DEFAULT 0,
                old_file_path TEXT,
                line_changes_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (commit_snapshot_id) REFERENCES commit_snapshots(id) ON DELETE CASCADE
            )
        """)
        
        # Clone tasks table - for async clone operations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clone_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id VARCHAR(64) UNIQUE NOT NULL,
                cloned_repo_id INTEGER,
                status VARCHAR(50) DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                current_operation TEXT,
                error_message TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cloned_repo_id) REFERENCES cloned_repositories(id) ON DELETE CASCADE
            )
        """)
        
        # User settings for clone path
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_clone_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                clone_base_path TEXT,
                auto_fetch_on_open BOOLEAN DEFAULT 1,
                store_diffs_in_db BOOLEAN DEFAULT 1,
                max_commits_to_analyze INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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


# =========================================
# PHASE 1: Repository Intelligence CRUD
# =========================================

def get_user_clone_settings(user_id: int) -> dict:
    """Get user's clone settings or return defaults"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_clone_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {
            "clone_base_path": DEFAULT_CLONE_PATH,
            "auto_fetch_on_open": True,
            "store_diffs_in_db": True,
            "max_commits_to_analyze": 100
        }


def update_user_clone_settings(user_id: int, settings: dict) -> bool:
    """Update or create user clone settings"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_clone_settings (user_id, clone_base_path, auto_fetch_on_open, store_diffs_in_db, max_commits_to_analyze)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                clone_base_path = excluded.clone_base_path,
                auto_fetch_on_open = excluded.auto_fetch_on_open,
                store_diffs_in_db = excluded.store_diffs_in_db,
                max_commits_to_analyze = excluded.max_commits_to_analyze,
                updated_at = CURRENT_TIMESTAMP
        """, (
            user_id,
            settings.get("clone_base_path", DEFAULT_CLONE_PATH),
            settings.get("auto_fetch_on_open", True),
            settings.get("store_diffs_in_db", True),
            settings.get("max_commits_to_analyze", 100)
        ))
        conn.commit()
        return True


# Cloned Repository CRUD
def create_cloned_repository(user_id: int, repo_data: dict) -> Optional[dict]:
    """Create a new cloned repository record"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO cloned_repositories (
                    user_id, repository_id, github_repo_id, name, full_name, owner,
                    local_path, clone_url, current_branch, clone_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                repo_data.get("repository_id"),
                repo_data["github_repo_id"],
                repo_data["name"],
                repo_data["full_name"],
                repo_data["owner"],
                repo_data["local_path"],
                repo_data["clone_url"],
                repo_data.get("branch", "main"),
                "pending"
            ))
            conn.commit()
            return get_cloned_repository(cursor.lastrowid)
        except sqlite3.IntegrityError as e:
            return None


def get_cloned_repository(repo_id: int) -> Optional[dict]:
    """Get a cloned repository by ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cloned_repositories WHERE id = ?", (repo_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_cloned_repository_by_path(local_path: str) -> Optional[dict]:
    """Get a cloned repository by local path"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cloned_repositories WHERE local_path = ?", (local_path,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_cloned_repositories(user_id: int) -> List[dict]:
    """Get all cloned repositories for a user"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM cloned_repositories 
            WHERE user_id = ? 
            ORDER BY updated_at DESC
        """, (user_id,))
        return [dict(row) for row in cursor.fetchall()]


def update_cloned_repository_status(repo_id: int, status: str, progress: int = None, 
                                     error: str = None, commit_sha: str = None) -> bool:
    """Update clone status and progress"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        updates = ["clone_status = ?", "updated_at = CURRENT_TIMESTAMP"]
        values = [status]
        
        if progress is not None:
            updates.append("clone_progress = ?")
            values.append(progress)
        if error is not None:
            updates.append("error_message = ?")
            values.append(error)
        if commit_sha is not None:
            updates.append("last_commit_sha = ?")
            values.append(commit_sha)
        if status == "completed":
            updates.append("cloned_at = CURRENT_TIMESTAMP")
            
        values.append(repo_id)
        cursor.execute(f"UPDATE cloned_repositories SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()
        return cursor.rowcount > 0


def update_cloned_repository_branch(repo_id: int, branch: str, commit_sha: str = None) -> bool:
    """Update current branch of a cloned repository"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if commit_sha:
            cursor.execute("""
                UPDATE cloned_repositories 
                SET current_branch = ?, last_commit_sha = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (branch, commit_sha, repo_id))
        else:
            cursor.execute("""
                UPDATE cloned_repositories 
                SET current_branch = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (branch, repo_id))
        conn.commit()
        return cursor.rowcount > 0


def delete_cloned_repository(repo_id: int) -> bool:
    """Delete a cloned repository record"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cloned_repositories WHERE id = ?", (repo_id,))
        conn.commit()
        return cursor.rowcount > 0


# Clone Task CRUD
def create_clone_task(task_id: str, cloned_repo_id: int = None) -> Optional[dict]:
    """Create a new clone task for async tracking"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO clone_tasks (task_id, cloned_repo_id, status, started_at)
            VALUES (?, ?, 'running', CURRENT_TIMESTAMP)
        """, (task_id, cloned_repo_id))
        conn.commit()
        return get_clone_task(task_id)


def get_clone_task(task_id: str) -> Optional[dict]:
    """Get a clone task by task ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clone_tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_clone_task(task_id: str, status: str = None, progress: int = None,
                      operation: str = None, error: str = None, 
                      cloned_repo_id: int = None) -> bool:
    """Update clone task progress"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        updates = []
        values = []
        
        if status:
            updates.append("status = ?")
            values.append(status)
            if status in ["completed", "failed"]:
                updates.append("completed_at = CURRENT_TIMESTAMP")
        if progress is not None:
            updates.append("progress = ?")
            values.append(progress)
        if operation:
            updates.append("current_operation = ?")
            values.append(operation)
        if error:
            updates.append("error_message = ?")
            values.append(error)
        if cloned_repo_id:
            updates.append("cloned_repo_id = ?")
            values.append(cloned_repo_id)
            
        if not updates:
            return False
            
        values.append(task_id)
        cursor.execute(f"UPDATE clone_tasks SET {', '.join(updates)} WHERE task_id = ?", values)
        conn.commit()
        return cursor.rowcount > 0


# Commit Snapshot CRUD
def save_commit_snapshot(cloned_repo_id: int, commit_data: dict) -> Optional[dict]:
    """Save a commit snapshot to the database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO commit_snapshots (
                    cloned_repo_id, commit_sha, parent_sha, commit_message,
                    author_name, author_email, committed_at,
                    total_files_changed, total_lines_added, total_lines_removed, diff_computed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cloned_repo_id, commit_sha) DO UPDATE SET
                    total_files_changed = excluded.total_files_changed,
                    total_lines_added = excluded.total_lines_added,
                    total_lines_removed = excluded.total_lines_removed,
                    diff_computed = excluded.diff_computed
            """, (
                cloned_repo_id,
                commit_data["commit_sha"],
                commit_data.get("parent_sha"),
                commit_data.get("message"),
                commit_data.get("author_name"),
                commit_data.get("author_email"),
                commit_data.get("committed_at"),
                commit_data.get("total_files_changed", 0),
                commit_data.get("total_lines_added", 0),
                commit_data.get("total_lines_removed", 0),
                commit_data.get("diff_computed", False)
            ))
            conn.commit()
            return get_commit_snapshot(cloned_repo_id, commit_data["commit_sha"])
        except sqlite3.IntegrityError:
            return None


def get_commit_snapshot(cloned_repo_id: int, commit_sha: str) -> Optional[dict]:
    """Get a commit snapshot by repo ID and commit SHA"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM commit_snapshots 
            WHERE cloned_repo_id = ? AND commit_sha = ?
        """, (cloned_repo_id, commit_sha))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_commit_snapshots(cloned_repo_id: int, limit: int = 50, offset: int = 0) -> List[dict]:
    """Get commit snapshots for a repository with pagination"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM commit_snapshots 
            WHERE cloned_repo_id = ?
            ORDER BY committed_at DESC
            LIMIT ? OFFSET ?
        """, (cloned_repo_id, limit, offset))
        return [dict(row) for row in cursor.fetchall()]


def get_commit_snapshot_by_id(snapshot_id: int) -> Optional[dict]:
    """Get a commit snapshot by its ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM commit_snapshots WHERE id = ?", (snapshot_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


# File Changes CRUD
def save_file_changes(commit_snapshot_id: int, files: List[dict]) -> bool:
    """Save file changes for a commit"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Delete existing file changes for this commit
        cursor.execute("DELETE FROM file_changes WHERE commit_snapshot_id = ?", (commit_snapshot_id,))
        
        # Insert new file changes
        for file_data in files:
            cursor.execute("""
                INSERT INTO file_changes (
                    commit_snapshot_id, file_path, change_type, language,
                    lines_added, lines_removed, old_file_path, line_changes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                commit_snapshot_id,
                file_data["file_path"],
                file_data["change_type"],
                file_data.get("language"),
                file_data.get("lines_added", 0),
                file_data.get("lines_removed", 0),
                file_data.get("old_file_path"),
                json.dumps(file_data.get("line_changes", []))
            ))
        
        conn.commit()
        return True


def get_file_changes(commit_snapshot_id: int) -> List[dict]:
    """Get file changes for a commit snapshot"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM file_changes 
            WHERE commit_snapshot_id = ?
            ORDER BY file_path
        """, (commit_snapshot_id,))
        
        results = []
        for row in cursor.fetchall():
            file_data = dict(row)
            # Parse JSON line changes
            if file_data.get("line_changes_json"):
                file_data["line_changes"] = json.loads(file_data["line_changes_json"])
            else:
                file_data["line_changes"] = []
            del file_data["line_changes_json"]
            results.append(file_data)
        
        return results


def get_full_commit_diff(cloned_repo_id: int, commit_sha: str) -> Optional[dict]:
    """Get full commit diff with all file changes (from DB cache)"""
    snapshot = get_commit_snapshot(cloned_repo_id, commit_sha)
    if not snapshot:
        return None
    
    files = get_file_changes(snapshot["id"])
    
    return {
        "commit": {
            "id": snapshot["commit_sha"],
            "parent_sha": snapshot["parent_sha"],
            "author": snapshot["author_name"],
            "email": snapshot["author_email"],
            "message": snapshot["commit_message"],
            "timestamp": snapshot["committed_at"]
        },
        "summary": {
            "total_files_changed": snapshot["total_files_changed"],
            "total_lines_added": snapshot["total_lines_added"],
            "total_lines_removed": snapshot["total_lines_removed"]
        },
        "files": files,
        "cached": True
    }



