"""
Webhook Routes for ETTA-X
Handles GitHub webhook events for automatic repository sync

When a developer pushes code to a connected repository:
1. GitHub sends a webhook event to ETTA-X
2. ETTA-X identifies the repository and automatically pulls the changes
3. Future: Run impact analysis and tests

Endpoints:
- POST /api/webhooks/github                    - Receive GitHub webhook events
- GET  /api/webhooks                           - List registered webhooks
- POST /api/webhooks/register/{repo_id}        - Register webhook for a repository
- DELETE /api/webhooks/{webhook_id}            - Remove a webhook
- GET  /api/webhooks/status                    - Get webhook service status
- GET  /api/webhooks/events/{repo_id}          - Get recent events for a repository
"""

import os
import hmac
import hashlib
import secrets
import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel

import httpx

from backend.app.database import (
    get_user_by_github_id,
    get_cloned_repository,
    get_user_cloned_repositories,
    update_cloned_repository_status,
    update_cloned_repository_branch,
    get_db_connection,
)

from backend.api.git_repo import RepositoryManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

# Thread pool for async operations
webhook_executor = ThreadPoolExecutor(max_workers=2)

# Webhook secret for verifying GitHub signatures
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


# ============================================
# Database Functions for Webhooks
# ============================================

def init_webhook_tables():
    """Initialize webhook-related database tables"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Webhook registrations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cloned_repo_id INTEGER NOT NULL,
                github_repo_id INTEGER NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                webhook_secret VARCHAR(64) NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                last_event_at TIMESTAMP,
                events_received INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cloned_repo_id) REFERENCES cloned_repositories(id) ON DELETE CASCADE,
                UNIQUE(cloned_repo_id)
            )
        """)
        
        # Webhook events log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                webhook_id INTEGER NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                delivery_id VARCHAR(64),
                sender VARCHAR(255),
                branch VARCHAR(100),
                commit_sha VARCHAR(40),
                commit_message TEXT,
                status VARCHAR(20) DEFAULT 'received',
                error_message TEXT,
                processed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (webhook_id) REFERENCES webhook_registrations(id) ON DELETE CASCADE
            )
        """)
        
        conn.commit()

# Initialize tables on module import
init_webhook_tables()


def create_webhook_registration(cloned_repo_id: int, github_repo_id: int, full_name: str) -> Optional[Dict]:
    """Create a webhook registration for a repository"""
    webhook_secret = secrets.token_hex(32)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO webhook_registrations (cloned_repo_id, github_repo_id, full_name, webhook_secret)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cloned_repo_id) DO UPDATE SET
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (cloned_repo_id, github_repo_id, full_name, webhook_secret))
            conn.commit()
            return get_webhook_by_repo_id(cloned_repo_id)
        except Exception as e:
            logger.error(f"Error creating webhook: {e}")
            return None


def get_webhook_by_repo_id(cloned_repo_id: int) -> Optional[Dict]:
    """Get webhook registration by cloned repository ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM webhook_registrations WHERE cloned_repo_id = ?
        """, (cloned_repo_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_webhook_by_github_repo(full_name: str) -> Optional[Dict]:
    """Get webhook registration by GitHub repository full name"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM webhook_registrations WHERE full_name = ? AND is_active = 1
        """, (full_name,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_webhooks_for_user(user_id: int) -> List[Dict]:
    """Get all webhook registrations for a user's repositories"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wr.*, cr.name, cr.local_path, cr.current_branch
            FROM webhook_registrations wr
            JOIN cloned_repositories cr ON wr.cloned_repo_id = cr.id
            WHERE cr.user_id = ?
            ORDER BY wr.updated_at DESC
        """, (user_id,))
        return [dict(row) for row in cursor.fetchall()]


def update_webhook_event_count(webhook_id: int):
    """Update the event count and last event timestamp"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE webhook_registrations 
            SET events_received = events_received + 1,
                last_event_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (webhook_id,))
        conn.commit()


def log_webhook_event(webhook_id: int, event_data: Dict) -> Optional[int]:
    """Log a webhook event"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO webhook_events 
            (webhook_id, event_type, delivery_id, sender, branch, commit_sha, commit_message, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            webhook_id,
            event_data.get("event_type", "push"),
            event_data.get("delivery_id"),
            event_data.get("sender"),
            event_data.get("branch"),
            event_data.get("commit_sha"),
            event_data.get("commit_message"),
            "received"
        ))
        conn.commit()
        return cursor.lastrowid


def update_webhook_event_status(event_id: int, status: str, error: str = None):
    """Update webhook event processing status"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE webhook_events 
            SET status = ?, error_message = ?, processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, error, event_id))
        conn.commit()


def get_webhook_events(webhook_id: int, limit: int = 20) -> List[Dict]:
    """Get recent webhook events"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM webhook_events 
            WHERE webhook_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (webhook_id, limit))
        return [dict(row) for row in cursor.fetchall()]


def delete_webhook(webhook_id: int) -> bool:
    """Delete a webhook registration"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM webhook_registrations WHERE id = ?", (webhook_id,))
        conn.commit()
        return cursor.rowcount > 0


# ============================================
# Helper Functions
# ============================================

async def get_current_user_id(request: Request) -> int:
    """Get the current authenticated user's database ID"""
    token = request.cookies.get("github_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        github_data = response.json()
        user = get_user_by_github_id(github_data.get('id'))
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return user['id']


def verify_github_signature(payload_body: bytes, signature: str, secret: str) -> bool:
    """Verify the GitHub webhook signature"""
    if not signature or not secret:
        return False
    
    try:
        expected_signature = "sha256=" + hmac.new(
            secret.encode(),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected_signature, signature)
    except Exception:
        return False


def process_push_event_sync(
    cloned_repo_id: int,
    local_path: str,
    branch: str,
    event_id: int
):
    """
    Synchronous function to process a push event (runs in thread pool)
    Fetches and pulls the latest changes
    """
    try:
        logger.info(f"Processing push event for repo {cloned_repo_id}")
        
        # Check if local path exists
        if not os.path.exists(local_path):
            update_webhook_event_status(event_id, "failed", "Local repository not found")
            return
        
        # Create repository manager
        manager = RepositoryManager(local_path)
        
        if not manager.repo:
            update_webhook_event_status(event_id, "failed", "Invalid git repository")
            return
        
        # Fetch all remotes
        logger.info(f"Fetching updates for {local_path}")
        fetch_success = manager.fetch_all()
        
        if not fetch_success:
            update_webhook_event_status(event_id, "failed", "Fetch failed")
            return
        
        # Check if the pushed branch matches current branch
        current_branch = manager.get_current_branch()
        
        if branch and current_branch == branch:
            # Pull changes for the current branch
            logger.info(f"Pulling changes for branch {branch}")
            pull_success = manager.pull(branch)
            
            if pull_success:
                # Update repository status in database
                new_sha = manager.get_current_commit_sha()
                update_cloned_repository_status(
                    cloned_repo_id,
                    "completed",
                    progress=100,
                    commit_sha=new_sha
                )
                update_webhook_event_status(event_id, "processed")
                logger.info(f"Successfully pulled changes. New SHA: {new_sha[:7]}")
            else:
                update_webhook_event_status(event_id, "failed", "Pull failed - may have conflicts")
        else:
            # Just fetch was done, note that it's a different branch
            logger.info(f"Push was to branch {branch}, current branch is {current_branch}. Only fetch performed.")
            update_webhook_event_status(event_id, "processed", f"Fetched only - push was to {branch}, not {current_branch}")
            
    except Exception as e:
        logger.error(f"Error processing push event: {e}")
        update_webhook_event_status(event_id, "failed", str(e))


# ============================================
# Request/Response Models
# ============================================

class WebhookRegistration(BaseModel):
    """Response model for webhook registration"""
    webhook_url: str
    secret: str
    events: List[str]


# ============================================
# Webhook Endpoints
# ============================================

@router.post("/github")
async def receive_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
):
    """
    Receive and process GitHub webhook events
    
    Automatically fetches and pulls changes when a push event is received
    for a connected repository.
    """
    # Get raw body for signature verification
    body = await request.body()
    
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Extract repository info from payload
    repository = payload.get("repository", {})
    repo_full_name = repository.get("full_name")
    
    if not repo_full_name:
        raise HTTPException(status_code=400, detail="Repository information missing")
    
    # Find the webhook registration for this repository
    webhook = get_webhook_by_github_repo(repo_full_name)
    
    if not webhook:
        # Repository not registered for webhooks
        logger.info(f"Webhook received for unregistered repo: {repo_full_name}")
        return {"status": "ignored", "message": "Repository not registered for webhooks"}
    
    # Verify signature if secret is set
    if webhook.get("webhook_secret"):
        if not verify_github_signature(body, x_hub_signature_256, webhook["webhook_secret"]):
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Update event count
    update_webhook_event_count(webhook["id"])
    
    # Handle different event types
    if x_github_event == "push":
        # Extract push event details
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else None
        
        head_commit = payload.get("head_commit", {})
        commit_sha = head_commit.get("id") or payload.get("after")
        commit_message = head_commit.get("message", "")[:200]
        
        pusher = payload.get("pusher", {})
        sender = pusher.get("name") or payload.get("sender", {}).get("login", "unknown")
        
        # Log the event
        event_id = log_webhook_event(webhook["id"], {
            "event_type": "push",
            "delivery_id": x_github_delivery,
            "sender": sender,
            "branch": branch,
            "commit_sha": commit_sha,
            "commit_message": commit_message
        })
        
        # Get the cloned repository
        cloned_repo = get_cloned_repository(webhook["cloned_repo_id"])
        
        if not cloned_repo:
            update_webhook_event_status(event_id, "failed", "Cloned repository not found")
            return {"status": "error", "message": "Cloned repository not found"}
        
        logger.info(f"Push event received for {repo_full_name} on branch {branch}")
        
        # Process in background
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            webhook_executor,
            process_push_event_sync,
            cloned_repo["id"],
            cloned_repo["local_path"],
            branch,
            event_id
        )
        
        return {
            "status": "processing",
            "message": f"Processing push event for {repo_full_name}",
            "branch": branch,
            "commit": commit_sha[:7] if commit_sha else None
        }
    
    elif x_github_event == "ping":
        # GitHub sends a ping event when webhook is first set up
        logger.info(f"Ping event received for {repo_full_name}")
        return {
            "status": "success",
            "message": "Webhook configured successfully",
            "zen": payload.get("zen", "")
        }
    
    else:
        # Log other events but don't process them
        log_webhook_event(webhook["id"], {
            "event_type": x_github_event,
            "delivery_id": x_github_delivery,
            "sender": payload.get("sender", {}).get("login", "unknown")
        })
        
        return {
            "status": "acknowledged",
            "message": f"Event type '{x_github_event}' received but not processed"
        }


@router.get("")
async def list_webhooks(request: Request):
    """List all webhook registrations for the current user"""
    user_id = await get_current_user_id(request)
    webhooks = get_all_webhooks_for_user(user_id)
    
    return {
        "webhooks": webhooks,
        "total": len(webhooks)
    }


@router.post("/register/{repo_id}")
async def register_webhook(repo_id: int, request: Request):
    """
    Register a webhook for a cloned repository
    
    Returns the webhook URL and secret that should be configured in GitHub
    """
    user_id = await get_current_user_id(request)
    
    # Get the cloned repository
    cloned_repo = get_cloned_repository(repo_id)
    
    if not cloned_repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if cloned_repo["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Create webhook registration
    webhook = create_webhook_registration(
        cloned_repo["id"],
        cloned_repo["github_repo_id"],
        cloned_repo["full_name"]
    )
    
    if not webhook:
        raise HTTPException(status_code=500, detail="Failed to create webhook registration")
    
    # Generate the webhook URL (use the server's public URL)
    base_url = os.getenv("WEBHOOK_BASE_URL", str(request.base_url).rstrip('/'))
    webhook_url = f"{base_url}/api/webhooks/github"
    
    return {
        "success": True,
        "webhook_id": webhook["id"],
        "webhook_url": webhook_url,
        "secret": webhook["webhook_secret"],
        "events": ["push"],
        "instructions": {
            "step1": f"Go to GitHub repository settings: https://github.com/{cloned_repo['full_name']}/settings/hooks/new",
            "step2": f"Set Payload URL to: {webhook_url}",
            "step3": "Set Content type to: application/json",
            "step4": f"Set Secret to: {webhook['webhook_secret']}",
            "step5": "Select 'Just the push event'",
            "step6": "Click 'Add webhook'"
        }
    }


@router.get("/status")
async def get_webhook_status(request: Request):
    """Get webhook service status and statistics"""
    user_id = await get_current_user_id(request)
    webhooks = get_all_webhooks_for_user(user_id)
    
    total_events = sum(w.get("events_received", 0) for w in webhooks)
    active_webhooks = sum(1 for w in webhooks if w.get("is_active"))
    
    return {
        "status": "active",
        "total_webhooks": len(webhooks),
        "active_webhooks": active_webhooks,
        "total_events_received": total_events,
        "webhook_endpoint": "/api/webhooks/github"
    }


@router.get("/events/{repo_id}")
async def get_repository_events(repo_id: int, request: Request, limit: int = 20):
    """Get recent webhook events for a repository"""
    user_id = await get_current_user_id(request)
    
    # Verify ownership
    cloned_repo = get_cloned_repository(repo_id)
    
    if not cloned_repo or cloned_repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # Get the webhook
    webhook = get_webhook_by_repo_id(repo_id)
    
    if not webhook:
        return {"events": [], "message": "No webhook registered for this repository"}
    
    events = get_webhook_events(webhook["id"], limit)
    
    return {
        "repository": cloned_repo["full_name"],
        "webhook_id": webhook["id"],
        "is_active": webhook["is_active"],
        "events": events
    }

@router.delete("/{webhook_id}")
async def remove_webhook(webhook_id: int, request: Request):
    """Remove a webhook registration"""
    user_id = await get_current_user_id(request)
    
    # Get the webhook first to verify ownership
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wr.*, cr.user_id
            FROM webhook_registrations wr
            JOIN cloned_repositories cr ON wr.cloned_repo_id = cr.id
            WHERE wr.id = ?
        """, (webhook_id,))
        row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    webhook = dict(row)
    
    if webhook["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Delete the webhook
    if delete_webhook(webhook_id):
        return {"success": True, "message": "Webhook deleted"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete webhook")


@router.post("/{repo_id}/pull")
async def manual_pull(repo_id: int, request: Request, background_tasks: BackgroundTasks):
    """Manually trigger a pull for a repository"""
    user_id = await get_current_user_id(request)
    
    cloned_repo = get_cloned_repository(repo_id)
    
    if not cloned_repo or cloned_repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(cloned_repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    # Get or create webhook for logging
    webhook = get_webhook_by_repo_id(repo_id)
    event_id = None
    
    if webhook:
        event_id = log_webhook_event(webhook["id"], {
            "event_type": "manual_pull",
            "sender": "user",
            "branch": cloned_repo.get("current_branch", "main")
        })
    
    # Process in background
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        webhook_executor,
        process_push_event_sync,
        cloned_repo["id"],
        cloned_repo["local_path"],
        cloned_repo.get("current_branch", "main"),
        event_id or 0
    )
    
    return {
        "status": "processing",
        "message": f"Pulling latest changes for {cloned_repo['full_name']}",
        "branch": cloned_repo.get("current_branch", "main")
    }
