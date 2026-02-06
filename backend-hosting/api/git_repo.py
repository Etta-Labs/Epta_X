"""
Git Repository module for ETTA-X application
Handles Git operations, GitHub API connections, and webhook management
"""

import os
import hmac
import hashlib
import secrets
from typing import Optional, List, Dict, Any, Tuple
import httpx
from git import Repo


class GitHubOAuthError(Exception):
    """Exception raised for OAuth scope/permission errors"""
    def __init__(self, message: str, missing_scopes: List[str] = None):
        super().__init__(message)
        self.missing_scopes = missing_scopes or []


class WebhookError(Exception):
    """Exception raised for webhook-related errors"""
    def __init__(self, message: str, status_code: int = None, can_retry: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.can_retry = can_retry


class GitHubAPI:
    """Class to interact with GitHub API for repository operations"""
    
    BASE_URL = "https://api.github.com"
    
    # Required OAuth scopes for full functionality
    REQUIRED_SCOPES = {"user", "repo", "admin:repo_hook"}
    WEBHOOK_REQUIRED_SCOPES = {"admin:repo_hook"}
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        self._token_scopes: Optional[List[str]] = None
    
    async def get_token_scopes(self) -> List[str]:
        """
        Fetch the OAuth scopes granted to the current access token.
        GitHub returns scopes in the 'X-OAuth-Scopes' header.
        
        Returns:
            List of scope strings (e.g., ['user', 'repo', 'admin:repo_hook'])
        """
        if self._token_scopes is not None:
            return self._token_scopes
        
        async with httpx.AsyncClient() as client:
            # Make a lightweight API call to get the scopes header
            response = await client.get(
                f"{self.BASE_URL}/user",
                headers=self.headers
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch token info: {response.status_code}")
            
            # GitHub returns scopes in this header
            scopes_header = response.headers.get("X-OAuth-Scopes", "")
            self._token_scopes = [s.strip() for s in scopes_header.split(",") if s.strip()]
            
            return self._token_scopes
    
    async def validate_scopes(self, required_scopes: set = None) -> Tuple[bool, List[str]]:
        """
        Validate that the token has the required OAuth scopes.
        
        Args:
            required_scopes: Set of required scope names. If None, uses REQUIRED_SCOPES.
        
        Returns:
            Tuple of (is_valid, missing_scopes)
        """
        if required_scopes is None:
            required_scopes = self.REQUIRED_SCOPES
        
        token_scopes = await self.get_token_scopes()
        token_scope_set = set(token_scopes)
        
        # Check for exact matches and parent scopes (e.g., 'admin:repo_hook' includes 'write:repo_hook')
        missing = []
        for required in required_scopes:
            if required not in token_scope_set:
                # Check for parent scope (GitHub scope hierarchy)
                parent_found = False
                if ":" in required:
                    # e.g., for 'write:repo_hook', check if 'admin:repo_hook' exists
                    parts = required.split(":")
                    admin_scope = f"admin:{parts[1]}" if parts[0] in ["read", "write"] else None
                    if admin_scope and admin_scope in token_scope_set:
                        parent_found = True
                
                if not parent_found:
                    missing.append(required)
        
        return len(missing) == 0, missing
    
    async def validate_webhook_permissions(self) -> Tuple[bool, List[str]]:
        """
        Validate that the token has permissions to create webhooks.
        
        Returns:
            Tuple of (has_permission, missing_scopes)
        """
        return await self.validate_scopes(self.WEBHOOK_REQUIRED_SCOPES)
    
    async def get_scope_info(self) -> Dict[str, Any]:
        """
        Get detailed information about token scopes.
        
        Returns:
            Dict with scope information and validation status
        """
        token_scopes = await self.get_token_scopes()
        is_valid, missing = await self.validate_scopes()
        has_webhook_perms, webhook_missing = await self.validate_webhook_permissions()
        
        return {
            "granted_scopes": token_scopes,
            "required_scopes": list(self.REQUIRED_SCOPES),
            "missing_scopes": missing,
            "is_fully_authorized": is_valid,
            "can_create_webhooks": has_webhook_perms,
            "webhook_missing_scopes": webhook_missing
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
    
    # ==================== COMMIT COMPARISON (for hosted environments) ====================
    
    async def compare_commits(self, owner: str, repo: str, base: str, head: str) -> Dict[str, Any]:
        """
        Compare two commits using GitHub API.
        This works without local git clone - ideal for hosted environments.
        
        Args:
            owner: Repository owner
            repo: Repository name
            base: Base commit SHA
            head: Head commit SHA
        
        Returns:
            Comparison data including files changed and diff
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/compare/{base}...{head}",
                headers=self.headers
            )
            
            if response.status_code == 404:
                raise Exception(f"Commits not found: {base}...{head}")
            
            if response.status_code != 200:
                raise Exception(f"Failed to compare commits: {response.status_code}")
            
            data = response.json()
            
            return {
                "status": data.get("status"),  # ahead, behind, identical, diverged
                "ahead_by": data.get("ahead_by", 0),
                "behind_by": data.get("behind_by", 0),
                "total_commits": data.get("total_commits", 0),
                "files": [
                    {
                        "path": f["filename"],
                        "status": f["status"],  # added, removed, modified, renamed
                        "additions": f.get("additions", 0),
                        "deletions": f.get("deletions", 0),
                        "changes": f.get("changes", 0),
                        "patch": f.get("patch", ""),  # The actual diff
                        "previous_filename": f.get("previous_filename"),
                    }
                    for f in data.get("files", [])
                ],
                "commits": [
                    {
                        "sha": c["sha"],
                        "message": c["commit"]["message"],
                        "author": c["commit"]["author"]["name"],
                        "date": c["commit"]["author"]["date"],
                    }
                    for c in data.get("commits", [])
                ]
            }
    
    async def get_commit_diff(self, owner: str, repo: str, commit_sha: str) -> Dict[str, Any]:
        """
        Get the diff for a single commit.
        
        Args:
            owner: Repository owner
            repo: Repository name
            commit_sha: Commit SHA
        
        Returns:
            Commit data with file changes
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/commits/{commit_sha}",
                headers=self.headers
            )
            
            if response.status_code == 404:
                raise Exception(f"Commit not found: {commit_sha}")
            
            if response.status_code != 200:
                raise Exception(f"Failed to get commit: {response.status_code}")
            
            data = response.json()
            
            return {
                "sha": data["sha"],
                "message": data["commit"]["message"],
                "author": data["commit"]["author"]["name"],
                "date": data["commit"]["author"]["date"],
                "stats": data.get("stats", {}),
                "files": [
                    {
                        "path": f["filename"],
                        "status": f["status"],
                        "additions": f.get("additions", 0),
                        "deletions": f.get("deletions", 0),
                        "patch": f.get("patch", ""),
                    }
                    for f in data.get("files", [])
                ]
            }
    
    # ==================== WEBHOOK MANAGEMENT ====================
    
    async def list_webhooks(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        """
        List all webhooks for a repository.
        
        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
        
        Returns:
            List of webhook configurations
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/hooks",
                headers=self.headers
            )
            
            if response.status_code == 404:
                raise WebhookError(f"Repository not found: {owner}/{repo}", 404)
            
            if response.status_code == 403:
                raise GitHubOAuthError(
                    "Missing permission to list webhooks. Requires 'admin:repo_hook' scope.",
                    missing_scopes=["admin:repo_hook"]
                )
            
            if response.status_code != 200:
                raise WebhookError(f"Failed to list webhooks: {response.status_code}", response.status_code)
            
            return response.json()
    
    async def get_webhook(self, owner: str, repo: str, hook_id: int) -> Dict[str, Any]:
        """
        Get a specific webhook by ID.
        
        Args:
            owner: Repository owner
            repo: Repository name
            hook_id: Webhook ID
        
        Returns:
            Webhook configuration
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/repos/{owner}/{repo}/hooks/{hook_id}",
                headers=self.headers
            )
            
            if response.status_code == 404:
                raise WebhookError(f"Webhook not found: {hook_id}", 404)
            
            if response.status_code != 200:
                raise WebhookError(f"Failed to get webhook: {response.status_code}", response.status_code)
            
            return response.json()
    
    async def find_existing_webhook(self, owner: str, repo: str, webhook_url: str) -> Optional[Dict[str, Any]]:
        """
        Find an existing webhook by URL.
        
        Args:
            owner: Repository owner
            repo: Repository name
            webhook_url: The webhook URL to search for
        
        Returns:
            Webhook configuration if found, None otherwise
        """
        try:
            webhooks = await self.list_webhooks(owner, repo)
            for hook in webhooks:
                if hook.get("config", {}).get("url") == webhook_url:
                    return hook
            return None
        except (WebhookError, GitHubOAuthError):
            return None
    
    async def create_webhook(
        self,
        owner: str,
        repo: str,
        webhook_url: str,
        secret: str,
        events: List[str] = None,
        active: bool = True
    ) -> Dict[str, Any]:
        """
        Create a new webhook for a repository.
        Automatically checks for existing webhooks and reuses them.
        
        Args:
            owner: Repository owner (username or organization)
            repo: Repository name
            webhook_url: Publicly reachable URL to receive webhook events
            secret: Shared secret for signature verification
            events: List of events to subscribe to (default: ["push", "pull_request"])
            active: Whether the webhook is active (default: True)
        
        Returns:
            Created webhook configuration
        
        Raises:
            GitHubOAuthError: If token lacks admin:repo_hook scope
            WebhookError: If webhook creation fails
        """
        if events is None:
            events = ["push", "pull_request"]
        
        # First, validate we have the required permissions
        has_perms, missing = await self.validate_webhook_permissions()
        if not has_perms:
            raise GitHubOAuthError(
                f"Missing required OAuth scopes for webhook creation: {', '.join(missing)}. "
                "Please re-authenticate with the required permissions.",
                missing_scopes=missing
            )
        
        # Check if webhook already exists (reuse instead of creating duplicate)
        existing_hook = await self.find_existing_webhook(owner, repo, webhook_url)
        if existing_hook:
            # Update the existing webhook if needed
            return await self.update_webhook(
                owner, repo, existing_hook["id"],
                webhook_url=webhook_url,
                secret=secret,
                events=events,
                active=active
            )
        
        # Create new webhook
        webhook_config = {
            "name": "web",
            "active": active,
            "events": events,
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0"  # Always require SSL verification
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/repos/{owner}/{repo}/hooks",
                headers=self.headers,
                json=webhook_config
            )
            
            if response.status_code == 404:
                raise WebhookError(f"Repository not found: {owner}/{repo}", 404)
            
            if response.status_code == 403:
                raise GitHubOAuthError(
                    "Missing permission to create webhooks. Requires 'admin:repo_hook' scope.",
                    missing_scopes=["admin:repo_hook"]
                )
            
            if response.status_code == 422:
                # Validation failed - could be duplicate URL or invalid config
                error_data = response.json()
                errors = error_data.get("errors", [])
                error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                raise WebhookError(f"Webhook validation failed: {error_msg}", 422)
            
            if response.status_code not in [200, 201]:
                raise WebhookError(
                    f"Failed to create webhook: {response.status_code} - {response.text}",
                    response.status_code,
                    can_retry=response.status_code >= 500
                )
            
            return response.json()
    
    async def update_webhook(
        self,
        owner: str,
        repo: str,
        hook_id: int,
        webhook_url: str = None,
        secret: str = None,
        events: List[str] = None,
        active: bool = None
    ) -> Dict[str, Any]:
        """
        Update an existing webhook.
        
        Args:
            owner: Repository owner
            repo: Repository name
            hook_id: Webhook ID to update
            webhook_url: New webhook URL (optional)
            secret: New secret (optional)
            events: New events list (optional)
            active: New active status (optional)
        
        Returns:
            Updated webhook configuration
        """
        # Build update payload with only provided fields
        config_updates = {}
        if webhook_url is not None:
            config_updates["url"] = webhook_url
        if secret is not None:
            config_updates["secret"] = secret
        config_updates["content_type"] = "json"
        
        payload = {}
        if config_updates:
            payload["config"] = config_updates
        if events is not None:
            payload["events"] = events
        if active is not None:
            payload["active"] = active
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.BASE_URL}/repos/{owner}/{repo}/hooks/{hook_id}",
                headers=self.headers,
                json=payload
            )
            
            if response.status_code == 404:
                raise WebhookError(f"Webhook not found: {hook_id}", 404)
            
            if response.status_code == 403:
                raise GitHubOAuthError(
                    "Missing permission to update webhooks. Requires 'admin:repo_hook' scope.",
                    missing_scopes=["admin:repo_hook"]
                )
            
            if response.status_code != 200:
                raise WebhookError(f"Failed to update webhook: {response.status_code}", response.status_code)
            
            return response.json()
    
    async def delete_webhook(self, owner: str, repo: str, hook_id: int) -> bool:
        """
        Delete a webhook.
        
        Args:
            owner: Repository owner
            repo: Repository name
            hook_id: Webhook ID to delete
        
        Returns:
            True if deletion was successful
        """
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.BASE_URL}/repos/{owner}/{repo}/hooks/{hook_id}",
                headers=self.headers
            )
            
            if response.status_code == 404:
                # Already deleted, consider it a success
                return True
            
            if response.status_code == 403:
                raise GitHubOAuthError(
                    "Missing permission to delete webhooks. Requires 'admin:repo_hook' scope.",
                    missing_scopes=["admin:repo_hook"]
                )
            
            if response.status_code != 204:
                raise WebhookError(f"Failed to delete webhook: {response.status_code}", response.status_code)
            
            return True
    
    async def ping_webhook(self, owner: str, repo: str, hook_id: int) -> bool:
        """
        Trigger a ping event for a webhook to test the connection.
        
        Args:
            owner: Repository owner
            repo: Repository name
            hook_id: Webhook ID to ping
        
        Returns:
            True if ping was sent successfully
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/repos/{owner}/{repo}/hooks/{hook_id}/pings",
                headers=self.headers
            )
            
            if response.status_code == 404:
                raise WebhookError(f"Webhook not found: {hook_id}", 404)
            
            if response.status_code != 204:
                raise WebhookError(f"Failed to ping webhook: {response.status_code}", response.status_code)
            
            return True


class WebhookPayloadParser:
    """
    Parser for GitHub webhook payloads.
    Extracts relevant information from push and pull_request events.
    """
    
    @staticmethod
    def parse_push_event(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a push event payload.
        
        Args:
            payload: Raw webhook payload
        
        Returns:
            Parsed push event data
        """
        commits = payload.get("commits", [])
        
        return {
            "event_type": "push",
            "repository": {
                "id": payload["repository"]["id"],
                "name": payload["repository"]["name"],
                "full_name": payload["repository"]["full_name"],
                "owner": payload["repository"]["owner"]["login"],
                "private": payload["repository"]["private"],
                "default_branch": payload["repository"].get("default_branch"),
                "clone_url": payload["repository"]["clone_url"],
            },
            "ref": payload.get("ref", ""),  # refs/heads/main
            "branch": payload.get("ref", "").replace("refs/heads/", ""),
            "before": payload.get("before"),  # Commit SHA before push
            "after": payload.get("after"),    # Commit SHA after push (latest)
            "created": payload.get("created", False),
            "deleted": payload.get("deleted", False),
            "forced": payload.get("forced", False),
            "commits": [
                {
                    "id": c["id"],
                    "message": c["message"],
                    "timestamp": c["timestamp"],
                    "author": c["author"],
                    "added": c.get("added", []),
                    "removed": c.get("removed", []),
                    "modified": c.get("modified", []),
                }
                for c in commits
            ],
            "head_commit": {
                "id": payload["head_commit"]["id"],
                "message": payload["head_commit"]["message"],
                "timestamp": payload["head_commit"]["timestamp"],
            } if payload.get("head_commit") else None,
            "pusher": payload.get("pusher", {}),
            "sender": {
                "id": payload["sender"]["id"],
                "login": payload["sender"]["login"],
            } if payload.get("sender") else None,
        }
    
    @staticmethod
    def parse_pull_request_event(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a pull_request event payload.
        
        Args:
            payload: Raw webhook payload
        
        Returns:
            Parsed pull request event data
        """
        pr = payload.get("pull_request", {})
        
        return {
            "event_type": "pull_request",
            "action": payload.get("action"),  # opened, closed, synchronize, etc.
            "repository": {
                "id": payload["repository"]["id"],
                "name": payload["repository"]["name"],
                "full_name": payload["repository"]["full_name"],
                "owner": payload["repository"]["owner"]["login"],
                "private": payload["repository"]["private"],
            },
            "pull_request": {
                "id": pr.get("id"),
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "head": {
                    "ref": pr.get("head", {}).get("ref"),  # Branch name
                    "sha": pr.get("head", {}).get("sha"),  # Latest commit SHA
                    "repo": pr.get("head", {}).get("repo", {}).get("full_name"),
                },
                "base": {
                    "ref": pr.get("base", {}).get("ref"),  # Target branch
                    "sha": pr.get("base", {}).get("sha"),
                    "repo": pr.get("base", {}).get("repo", {}).get("full_name"),
                },
                "merged": pr.get("merged", False),
                "mergeable": pr.get("mergeable"),
                "draft": pr.get("draft", False),
            },
            "sender": {
                "id": payload["sender"]["id"],
                "login": payload["sender"]["login"],
            } if payload.get("sender") else None,
        }
    
    @staticmethod
    def parse(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a webhook payload based on event type.
        
        Args:
            event_type: GitHub event type (from X-GitHub-Event header)
            payload: Raw webhook payload
        
        Returns:
            Parsed event data
        """
        if event_type == "push":
            return WebhookPayloadParser.parse_push_event(payload)
        elif event_type == "pull_request":
            return WebhookPayloadParser.parse_pull_request_event(payload)
        elif event_type == "ping":
            return {
                "event_type": "ping",
                "zen": payload.get("zen"),
                "hook_id": payload.get("hook_id"),
                "repository": {
                    "id": payload["repository"]["id"],
                    "full_name": payload["repository"]["full_name"],
                } if payload.get("repository") else None,
            }
        else:
            return {
                "event_type": event_type,
                "raw_payload": payload,
            }


class WebhookSignatureVerifier:
    """
    Verifies GitHub webhook signatures using HMAC-SHA256.
    """
    
    @staticmethod
    def generate_secret() -> str:
        """Generate a cryptographically secure webhook secret."""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def compute_signature(payload: bytes, secret: str) -> str:
        """
        Compute the expected HMAC-SHA256 signature for a payload.
        
        Args:
            payload: Raw request body bytes
            secret: Webhook secret
        
        Returns:
            Signature string in format "sha256=<hex_digest>"
        """
        mac = hmac.new(
            secret.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha256
        )
        return f"sha256={mac.hexdigest()}"
    
    @staticmethod
    def verify_signature(payload: bytes, secret: str, signature: str) -> bool:
        """
        Verify the GitHub webhook signature.
        
        Args:
            payload: Raw request body bytes
            secret: Webhook secret
            signature: X-Hub-Signature-256 header value
        
        Returns:
            True if signature is valid, False otherwise
        """
        if not signature or not signature.startswith("sha256="):
            return False
        
        expected_signature = WebhookSignatureVerifier.compute_signature(payload, secret)
        
        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(expected_signature, signature)


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
