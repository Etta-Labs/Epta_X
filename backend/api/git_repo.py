"""
Git Repository module for ETTA-X application
Handles Git operations and GitHub API connections
"""

import os
from typing import Optional, List, Dict, Any
import httpx
from git import Repo


class GitHubAPI:
    """Class to interact with GitHub API for repository operations"""
    
    BASE_URL = "https://api.github.com"
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }
    
    async def get_user_repos(self, per_page: int = 100, page: int = 1) -> List[Dict[str, Any]]:
        """
        Fetch all repositories the authenticated user has access to.
        This includes owned repos and repos they have permission to access.
        """
        async with httpx.AsyncClient() as client:
            # Get repos the user owns or has explicit access to
            response = await client.get(
                f"{self.BASE_URL}/user/repos",
                headers=self.headers,
                params={
                    "per_page": per_page,
                    "page": page,
                    "sort": "updated",
                    "direction": "desc",
                    "affiliation": "owner,collaborator,organization_member"
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch repos: {response.status_code}")
            
            repos = response.json()
            
            # Format the response
            return [
                {
                    "id": repo["id"],
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                    "private": repo["private"],
                    "owner": repo["owner"]["login"],
                    "default_branch": repo["default_branch"],
                    "clone_url": repo["clone_url"],
                    "ssh_url": repo["ssh_url"],
                    "html_url": repo["html_url"],
                    "description": repo.get("description"),
                    "language": repo.get("language"),
                    "updated_at": repo["updated_at"],
                }
                for repo in repos
            ]
    
    async def get_repo_branches(self, owner: str, repo: str, per_page: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch all branches for a specific repository.
        
        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
            per_page: Number of branches per page
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/branches",
                headers=self.headers,
                params={"per_page": per_page}
            )
            
            if response.status_code == 404:
                raise Exception(f"Repository not found: {owner}/{repo}")
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch branches: {response.status_code}")
            
            branches = response.json()
            
            return [
                {
                    "name": branch["name"],
                    "protected": branch.get("protected", False),
                    "commit_sha": branch["commit"]["sha"][:7] if branch.get("commit") else None,
                }
                for branch in branches
            ]
    
    async def get_repo_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific repository.
        
        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}",
                headers=self.headers
            )
            
            if response.status_code == 404:
                raise Exception(f"Repository not found: {owner}/{repo}")
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch repo info: {response.status_code}")
            
            repo_data = response.json()
            
            return {
                "id": repo_data["id"],
                "name": repo_data["name"],
                "full_name": repo_data["full_name"],
                "private": repo_data["private"],
                "owner": repo_data["owner"]["login"],
                "default_branch": repo_data["default_branch"],
                "clone_url": repo_data["clone_url"],
                "ssh_url": repo_data["ssh_url"],
                "html_url": repo_data["html_url"],
                "description": repo_data.get("description"),
                "language": repo_data.get("language"),
                "size": repo_data.get("size"),
                "stargazers_count": repo_data.get("stargazers_count"),
                "forks_count": repo_data.get("forks_count"),
                "created_at": repo_data["created_at"],
                "updated_at": repo_data["updated_at"],
            }


class GitRepository:
    """Class to manage local Git repository operations"""
    
    def __init__(self, repo_path: str = None):
        self.repo_path = repo_path
        self.repo = None
        self.default_branch = "main"
        
        if repo_path and os.path.exists(repo_path):
            self.repo = Repo(repo_path)
    
    def clone(self, url: str, destination: str, branch: str = None) -> Repo:
        """Clone a repository from URL"""
        branch = branch or self.default_branch
        self.repo = Repo.clone_from(url, destination, branch=branch)
        self.repo_path = destination
        return self.repo
    
    def init(self, path: str) -> Repo:
        """Initialize a new Git repository"""
        self.repo = Repo.init(path)
        self.repo_path = path
        return self.repo
    
    def get_current_branch(self) -> str:
        """Get the current active branch name"""
        if self.repo:
            return self.repo.active_branch.name
        return None
    
    def get_remote_url(self) -> str:
        """Get the origin remote URL"""
        if self.repo and self.repo.remotes:
            return self.repo.remotes.origin.url
        return None
    
    def get_all_branches(self) -> List[str]:
        """Get all local branches"""
        if self.repo:
            return [branch.name for branch in self.repo.branches]
        return []
    
    def checkout_branch(self, branch_name: str) -> bool:
        """Checkout to a specific branch"""
        if self.repo:
            try:
                self.repo.git.checkout(branch_name)
                return True
            except Exception:
                return False
        return False
