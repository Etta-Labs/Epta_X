"""
Repository Intelligence API Routes
PHASE 1: Clone, Branch, Diff, and Commit Operations

Endpoints:
- POST /api/repos/clone          - Clone a repository (async with progress)
- GET  /api/repos/clone/{task_id} - Get clone task status
- GET  /api/repos/cloned         - List user's cloned repositories
- GET  /api/repos/{id}           - Get cloned repository details
- DELETE /api/repos/{id}         - Delete cloned repository
- POST /api/repos/{id}/fetch     - Fetch updates from remote
- GET  /api/repos/{id}/branches  - List branches
- POST /api/repos/{id}/checkout  - Checkout a branch
- GET  /api/repos/{id}/commits   - Get commit history
- GET  /api/repos/{id}/diff/{sha} - Get commit diff
- GET  /api/repos/{id}/diff      - Get uncommitted changes
- GET  /api/repos/{id}/compare   - Compare two commits
- GET  /api/repos/{id}/files     - Get file tree
- GET  /api/repos/{id}/file      - Get file content
- GET  /api/repos/settings       - Get clone settings
- PUT  /api/repos/settings       - Update clone settings
"""

import os
import secrets
import shutil
import asyncio
from typing import Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel

from backend.app.database import (
    get_user_by_github_id,
    get_user_clone_settings,
    update_user_clone_settings,
    create_cloned_repository,
    get_cloned_repository,
    get_cloned_repository_by_path,
    get_user_cloned_repositories,
    update_cloned_repository_status,
    update_cloned_repository_branch,
    delete_cloned_repository,
    create_clone_task,
    get_clone_task,
    update_clone_task,
    save_commit_snapshot,
    get_commit_snapshot,
    get_commit_snapshots,
    save_file_changes,
    get_file_changes,
    get_full_commit_diff,
    DEFAULT_CLONE_PATH
)

from backend.api.git_repo import RepositoryManager, GitHubAPI

import httpx

# Create router
router = APIRouter(prefix="/api/repos", tags=["Repository Intelligence"])

# Thread pool for async clone operations
executor = ThreadPoolExecutor(max_workers=4)


# ============================================
# Request/Response Models
# ============================================

class CloneRequest(BaseModel):
    """Request model for cloning a repository"""
    clone_url: str
    full_name: str  # owner/repo
    name: str
    owner: str
    github_repo_id: int
    branch: Optional[str] = None
    custom_path: Optional[str] = None


class CheckoutRequest(BaseModel):
    """Request model for checking out a branch"""
    branch: str
    create: bool = False


class CloneSettingsUpdate(BaseModel):
    """Request model for updating clone settings"""
    clone_base_path: Optional[str] = None
    auto_fetch_on_open: Optional[bool] = None
    store_diffs_in_db: Optional[bool] = None
    max_commits_to_analyze: Optional[int] = None


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


def get_clone_path(user_id: int, repo_full_name: str, custom_path: str = None) -> str:
    """Generate the local path for cloning a repository"""
    if custom_path:
        return custom_path
    
    settings = get_user_clone_settings(user_id)
    base_path = settings.get("clone_base_path", DEFAULT_CLONE_PATH)
    
    # Ensure base path exists
    os.makedirs(base_path, exist_ok=True)
    
    # Create path: base_path/owner/repo
    owner, repo = repo_full_name.split('/')
    return os.path.join(base_path, owner, repo)


def clone_repository_sync(
    task_id: str,
    clone_url: str,
    destination: str,
    branch: str,
    repo_data: dict,
    user_id: int,
    store_diffs: bool = True
):
    """
    Synchronous function to clone repository (runs in thread pool)
    Updates task progress as clone proceeds
    """
    try:
        # Update task status
        update_clone_task(task_id, status="running", progress=0, operation="Starting clone")
        
        def progress_callback(progress: int, operation: str):
            """Callback to update clone progress"""
            update_clone_task(task_id, progress=progress, operation=operation)
        
        # Perform the clone
        repo_manager = RepositoryManager.clone_repository(
            url=clone_url,
            destination=destination,
            branch=branch,
            progress_callback=progress_callback
        )
        
        # Create database record for cloned repo
        cloned_repo = create_cloned_repository(user_id, {
            "github_repo_id": repo_data["github_repo_id"],
            "name": repo_data["name"],
            "full_name": repo_data["full_name"],
            "owner": repo_data["owner"],
            "local_path": destination,
            "clone_url": clone_url,
            "branch": branch or repo_manager.get_current_branch() or "main"
        })
        
        if cloned_repo:
            # Update with commit SHA
            current_sha = repo_manager.get_current_commit_sha()
            update_cloned_repository_status(
                cloned_repo["id"], 
                "completed", 
                progress=100,
                commit_sha=current_sha
            )
            
            # Link task to cloned repo
            update_clone_task(task_id, cloned_repo_id=cloned_repo["id"])
            
            # Optionally store initial commit diffs
            if store_diffs:
                try:
                    # Get recent commits and store their diffs
                    commits = repo_manager.get_commit_history(limit=10)
                    for commit in commits[:5]:  # Store last 5 commits
                        diff_data = repo_manager.get_commit_diff(commit["sha"])
                        if diff_data and "error" not in diff_data:
                            snapshot = save_commit_snapshot(cloned_repo["id"], {
                                "commit_sha": commit["sha"],
                                "parent_sha": commit.get("parent_sha"),
                                "message": commit["message"],
                                "author_name": commit["author_name"],
                                "author_email": commit["author_email"],
                                "committed_at": commit["committed_at"],
                                "total_files_changed": diff_data["summary"]["total_files_changed"],
                                "total_lines_added": diff_data["summary"]["total_lines_added"],
                                "total_lines_removed": diff_data["summary"]["total_lines_removed"],
                                "diff_computed": True
                            })
                            if snapshot:
                                save_file_changes(snapshot["id"], diff_data["files"])
                except Exception:
                    pass  # Don't fail clone if diff storage fails
        
        # Mark task complete
        update_clone_task(task_id, status="completed", progress=100, operation="Clone complete")
        
    except Exception as e:
        # Mark task as failed
        update_clone_task(task_id, status="failed", error=str(e))
        
        # Clean up partial clone
        if os.path.exists(destination):
            try:
                shutil.rmtree(destination)
            except:
                pass


# ============================================
# Clone Endpoints
# ============================================

@router.post("/clone")
async def start_clone(
    request: Request,
    clone_request: CloneRequest,
    background_tasks: BackgroundTasks
):
    """
    Start cloning a repository (async operation)
    
    Returns a task_id that can be used to poll for progress
    """
    user_id = await get_current_user_id(request)
    
    # Get clone path
    destination = get_clone_path(
        user_id, 
        clone_request.full_name, 
        clone_request.custom_path
    )
    
    # Check if already cloned at this path
    existing = get_cloned_repository_by_path(destination)
    if existing and existing["clone_status"] == "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Repository already cloned at {destination}"
        )
    
    # Generate task ID
    task_id = secrets.token_urlsafe(32)
    
    # Create task record
    create_clone_task(task_id)
    
    # Get user settings for diff storage preference
    settings = get_user_clone_settings(user_id)
    store_diffs = settings.get("store_diffs_in_db", True)
    
    # Prepare repo data
    repo_data = {
        "github_repo_id": clone_request.github_repo_id,
        "name": clone_request.name,
        "full_name": clone_request.full_name,
        "owner": clone_request.owner,
    }
    
    # Get GitHub token for authenticated clone (for private repos)
    token = request.cookies.get("github_token")
    clone_url = clone_request.clone_url
    
    # Inject token into URL for private repos
    if token and clone_url.startswith("https://"):
        clone_url = clone_url.replace("https://", f"https://{token}@")
    
    # Start clone in background thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        executor,
        clone_repository_sync,
        task_id,
        clone_url,
        destination,
        clone_request.branch,
        repo_data,
        user_id,
        store_diffs
    )
    
    return {
        "task_id": task_id,
        "status": "started",
        "destination": destination,
        "message": "Clone operation started. Poll /api/repos/clone/{task_id} for progress."
    }


@router.get("/clone/{task_id}")
async def get_clone_status(task_id: str):
    """Get the status of a clone operation"""
    task = get_clone_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Clone task not found")
    
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "current_operation": task["current_operation"],
        "error_message": task["error_message"],
        "cloned_repo_id": task["cloned_repo_id"],
        "started_at": task["started_at"],
        "completed_at": task["completed_at"]
    }


# ============================================
# Cloned Repository Management
# ============================================

@router.get("/cloned")
async def list_cloned_repositories(request: Request):
    """List all cloned repositories for the current user"""
    user_id = await get_current_user_id(request)
    repos = get_user_cloned_repositories(user_id)
    
    # Add existence check for local paths
    for repo in repos:
        repo["local_exists"] = os.path.exists(repo["local_path"])
    
    return {"repositories": repos}


# ============================================
# Settings (must be before /{repo_id} routes)
# ============================================

@router.get("/settings")
async def get_settings(request: Request):
    """Get current clone settings for the user"""
    user_id = await get_current_user_id(request)
    settings = get_user_clone_settings(user_id)
    
    return {
        "clone_base_path": settings.get("clone_base_path", DEFAULT_CLONE_PATH),
        "auto_fetch_on_open": settings.get("auto_fetch_on_open", True),
        "store_diffs_in_db": settings.get("store_diffs_in_db", True),
        "max_commits_to_analyze": settings.get("max_commits_to_analyze", 100),
        "default_clone_path": DEFAULT_CLONE_PATH
    }


@router.put("/settings")
async def update_settings(request: Request, settings: CloneSettingsUpdate):
    """Update clone settings for the user"""
    user_id = await get_current_user_id(request)
    
    update_data = {}
    if settings.clone_base_path is not None:
        update_data["clone_base_path"] = settings.clone_base_path
    if settings.auto_fetch_on_open is not None:
        update_data["auto_fetch_on_open"] = settings.auto_fetch_on_open
    if settings.store_diffs_in_db is not None:
        update_data["store_diffs_in_db"] = settings.store_diffs_in_db
    if settings.max_commits_to_analyze is not None:
        update_data["max_commits_to_analyze"] = settings.max_commits_to_analyze
    
    if update_data:
        # Merge with existing settings
        current = get_user_clone_settings(user_id)
        current.update(update_data)
        update_user_clone_settings(user_id, current)
    
    return {"success": True, "settings": get_user_clone_settings(user_id)}


@router.get("/{repo_id}")
async def get_repository_details(repo_id: int, request: Request):
    """Get details of a specific cloned repository"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # Check if local path exists
    repo["local_exists"] = os.path.exists(repo["local_path"])
    
    # If exists, get current state
    if repo["local_exists"]:
        try:
            manager = RepositoryManager(repo["local_path"])
            repo["current_branch"] = manager.get_current_branch()
            repo["current_commit"] = manager.get_current_commit_sha()
        except:
            pass
    
    return repo


@router.delete("/{repo_id}")
async def delete_repository(repo_id: int, request: Request, delete_files: bool = False):
    """
    Delete a cloned repository record
    
    Args:
        delete_files: If True, also delete local files
    """
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # Optionally delete local files
    if delete_files and os.path.exists(repo["local_path"]):
        try:
            shutil.rmtree(repo["local_path"])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete files: {str(e)}")
    
    # Delete database record
    delete_cloned_repository(repo_id)
    
    return {"success": True, "message": "Repository deleted"}


@router.post("/{repo_id}/fetch")
async def fetch_repository(repo_id: int, request: Request):
    """Fetch updates from remote"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    try:
        manager = RepositoryManager(repo["local_path"])
        success = manager.fetch_all()
        
        if success:
            return {"success": True, "message": "Fetch complete"}
        else:
            raise HTTPException(status_code=500, detail="Fetch failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Branch Management
# ============================================

@router.get("/{repo_id}/branches")
async def list_branches(repo_id: int, request: Request, include_remote: bool = True):
    """List all branches for a cloned repository"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    try:
        manager = RepositoryManager(repo["local_path"])
        branches = manager.get_all_branches(include_remote=include_remote)
        current = manager.get_current_branch()
        
        return {
            "current_branch": current,
            "branches": branches
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{repo_id}/checkout")
async def checkout_branch(repo_id: int, request: Request, checkout: CheckoutRequest):
    """Checkout a specific branch"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    try:
        manager = RepositoryManager(repo["local_path"])
        success = manager.checkout_branch(checkout.branch, create=checkout.create)
        
        if success:
            # Update database record
            current_sha = manager.get_current_commit_sha()
            update_cloned_repository_branch(repo_id, checkout.branch, current_sha)
            
            return {
                "success": True,
                "branch": checkout.branch,
                "commit_sha": current_sha
            }
        else:
            raise HTTPException(status_code=400, detail=f"Failed to checkout branch: {checkout.branch}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Commit History & Diff
# ============================================

@router.get("/{repo_id}/commits")
async def get_commits(
    repo_id: int,
    request: Request,
    branch: Optional[str] = None,
    limit: int = 50,
    skip: int = 0
):
    """Get commit history for a repository"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    try:
        manager = RepositoryManager(repo["local_path"])
        commits = manager.get_commit_history(branch=branch, limit=limit, skip=skip)
        
        return {
            "branch": branch or manager.get_current_branch(),
            "total_returned": len(commits),
            "skip": skip,
            "commits": commits
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}/diff/{commit_sha}")
async def get_commit_diff(repo_id: int, commit_sha: str, request: Request):
    """
    Get detailed diff for a specific commit
    
    Returns the structured diff format with file changes and line-level details.
    Results are cached in the database for fast retrieval.
    """
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    # Check if we have cached diff in database
    settings = get_user_clone_settings(user_id)
    if settings.get("store_diffs_in_db", True):
        cached_diff = get_full_commit_diff(repo_id, commit_sha)
        if cached_diff and cached_diff.get("files"):
            cached_diff["branch"] = repo["current_branch"]
            return cached_diff
    
    # Compute diff from git
    try:
        manager = RepositoryManager(repo["local_path"])
        diff_data = manager.get_commit_diff(commit_sha)
        
        if "error" in diff_data:
            raise HTTPException(status_code=400, detail=diff_data["error"])
        
        # Cache the diff if enabled
        if settings.get("store_diffs_in_db", True):
            try:
                snapshot = save_commit_snapshot(repo_id, {
                    "commit_sha": diff_data["commit"]["id"],
                    "parent_sha": None,  # Would need to fetch this
                    "message": diff_data["commit"]["message"],
                    "author_name": diff_data["commit"]["author"],
                    "author_email": diff_data["commit"]["email"],
                    "committed_at": diff_data["commit"]["timestamp"],
                    "total_files_changed": diff_data["summary"]["total_files_changed"],
                    "total_lines_added": diff_data["summary"]["total_lines_added"],
                    "total_lines_removed": diff_data["summary"]["total_lines_removed"],
                    "diff_computed": True
                })
                if snapshot:
                    save_file_changes(snapshot["id"], diff_data["files"])
            except:
                pass  # Don't fail if caching fails
        
        diff_data["branch"] = repo["current_branch"]
        return diff_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}/diff")
async def get_uncommitted_diff(repo_id: int, request: Request):
    """Get uncommitted changes in the working directory"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    try:
        manager = RepositoryManager(repo["local_path"])
        diff_data = manager.get_uncommitted_changes()
        
        if "error" in diff_data:
            raise HTTPException(status_code=400, detail=diff_data["error"])
        
        diff_data["branch"] = manager.get_current_branch()
        return diff_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}/compare")
async def compare_commits(
    repo_id: int,
    request: Request,
    from_sha: str,
    to_sha: str
):
    """Compare two commits and return the diff between them"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    try:
        manager = RepositoryManager(repo["local_path"])
        diff_data = manager.compare_commits(from_sha, to_sha)
        
        if "error" in diff_data:
            raise HTTPException(status_code=400, detail=diff_data["error"])
        
        return diff_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# File Operations
# ============================================

@router.get("/{repo_id}/files")
async def get_file_tree(
    repo_id: int,
    request: Request,
    path: str = "",
    commit_sha: Optional[str] = None
):
    """Get file tree structure for a repository"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    try:
        manager = RepositoryManager(repo["local_path"])
        files = manager.get_file_tree(commit_sha=commit_sha, path=path)
        
        return {
            "path": path or "/",
            "commit": commit_sha or manager.get_current_commit_sha()[:7],
            "items": files
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_id}/file")
async def get_file_content(
    repo_id: int,
    request: Request,
    path: str,
    commit_sha: Optional[str] = None
):
    """Get content of a specific file"""
    user_id = await get_current_user_id(request)
    repo = get_cloned_repository(repo_id)
    
    if not repo or repo["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not os.path.exists(repo["local_path"]):
        raise HTTPException(status_code=404, detail="Local repository not found")
    
    try:
        manager = RepositoryManager(repo["local_path"])
        content = manager.get_file_content(path, commit_sha=commit_sha)
        
        if content is None:
            raise HTTPException(status_code=404, detail="File not found")
        
        return {
            "path": path,
            "commit": commit_sha or manager.get_current_commit_sha()[:7],
            "content": content
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
