"""
ETTA-X Backend API Module

Phase 1: Repository Intelligence
- git_repo.py: Git operations and GitHub API
- repo_routes.py: FastAPI routes for repository management
"""

from backend.api.git_repo import GitHubAPI, GitRepository, RepositoryManager
from backend.api.repo_routes import router as repo_router

__all__ = [
    "GitHubAPI",
    "GitRepository", 
    "RepositoryManager",
    "repo_router"
]
