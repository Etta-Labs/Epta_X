"""
Git Repository module for ETTA-X application
Handles Git operations and GitHub API connections

PHASE 1: Repository Intelligence
- Repository cloning with progress tracking
- Branch selection and management
- Git diff for commits and PRs
- Store changed files per commit
"""

import os
import re
import shutil
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
import httpx
from git import Repo, RemoteProgress
from git.exc import GitCommandError, InvalidGitRepositoryError


# Language detection based on file extension
LANGUAGE_MAP = {
    '.py': 'python',
    '.js': 'javascript',
    '.ts': 'typescript',
    '.jsx': 'javascript',
    '.tsx': 'typescript',
    '.java': 'java',
    '.c': 'c',
    '.cpp': 'cpp',
    '.h': 'c',
    '.hpp': 'cpp',
    '.cs': 'csharp',
    '.go': 'go',
    '.rs': 'rust',
    '.rb': 'ruby',
    '.php': 'php',
    '.swift': 'swift',
    '.kt': 'kotlin',
    '.scala': 'scala',
    '.r': 'r',
    '.R': 'r',
    '.sql': 'sql',
    '.html': 'html',
    '.css': 'css',
    '.scss': 'scss',
    '.sass': 'sass',
    '.less': 'less',
    '.json': 'json',
    '.xml': 'xml',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.md': 'markdown',
    '.sh': 'bash',
    '.bash': 'bash',
    '.ps1': 'powershell',
    '.bat': 'batch',
    '.dockerfile': 'dockerfile',
    '.vue': 'vue',
    '.svelte': 'svelte',
}


def detect_language(file_path: str) -> Optional[str]:
    """Detect programming language from file extension"""
    _, ext = os.path.splitext(file_path.lower())
    
    # Handle Dockerfile specially
    if os.path.basename(file_path).lower() == 'dockerfile':
        return 'dockerfile'
    
    return LANGUAGE_MAP.get(ext)


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


class CloneProgressHandler(RemoteProgress):
    """Progress handler for git clone operations with callback support"""
    
    def __init__(self, callback: Callable[[int, str], None] = None):
        super().__init__()
        self.callback = callback
        self.current_operation = "Initializing"
        self._last_progress = 0
    
    def update(self, op_code, cur_count, max_count=None, message=''):
        """Called by GitPython during clone progress"""
        # Determine operation type
        if op_code & self.COUNTING:
            self.current_operation = "Counting objects"
        elif op_code & self.COMPRESSING:
            self.current_operation = "Compressing objects"
        elif op_code & self.WRITING:
            self.current_operation = "Writing objects"
        elif op_code & self.RECEIVING:
            self.current_operation = "Receiving objects"
        elif op_code & self.RESOLVING:
            self.current_operation = "Resolving deltas"
        elif op_code & self.CHECKING_OUT:
            self.current_operation = "Checking out files"
        
        # Calculate progress percentage
        if max_count and max_count > 0:
            progress = int((cur_count / max_count) * 100)
        else:
            progress = self._last_progress
        
        self._last_progress = progress
        
        # Call the callback with progress info
        if self.callback:
            self.callback(progress, self.current_operation)


class RepositoryManager:
    """
    Advanced repository manager for ETTA-X Phase 1: Repository Intelligence
    
    Handles:
    - Repository cloning with progress tracking
    - Branch management
    - Commit history retrieval
    - Git diff parsing and analysis
    - File change detection per commit
    """
    
    def __init__(self, repo_path: str = None):
        self.repo_path = repo_path
        self.repo: Optional[Repo] = None
        
        if repo_path and os.path.exists(repo_path):
            try:
                self.repo = Repo(repo_path)
            except InvalidGitRepositoryError:
                self.repo = None
    
    @staticmethod
    def clone_repository(
        url: str,
        destination: str,
        branch: str = None,
        progress_callback: Callable[[int, str], None] = None
    ) -> 'RepositoryManager':
        """
        Clone a repository with progress tracking
        
        Args:
            url: Repository URL (HTTPS or SSH)
            destination: Local path to clone to
            branch: Specific branch to clone (optional)
            progress_callback: Function called with (progress_percent, operation_name)
        
        Returns:
            RepositoryManager instance for the cloned repo
        """
        # Ensure destination directory exists
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        
        # Remove existing directory if it exists
        if os.path.exists(destination):
            shutil.rmtree(destination)
        
        # Create progress handler
        progress_handler = CloneProgressHandler(progress_callback)
        
        # Clone the repository
        clone_kwargs = {
            'url': url,
            'to_path': destination,
            'progress': progress_handler,
        }
        
        if branch:
            clone_kwargs['branch'] = branch
        
        repo = Repo.clone_from(**clone_kwargs)
        
        return RepositoryManager(destination)
    
    def get_current_branch(self) -> Optional[str]:
        """Get the current active branch name"""
        if not self.repo:
            return None
        try:
            return self.repo.active_branch.name
        except TypeError:
            # Detached HEAD state
            return None
    
    def get_current_commit_sha(self) -> Optional[str]:
        """Get the current HEAD commit SHA"""
        if not self.repo:
            return None
        return self.repo.head.commit.hexsha
    
    def get_all_branches(self, include_remote: bool = False) -> List[Dict[str, Any]]:
        """Get all branches with metadata"""
        if not self.repo:
            return []
        
        branches = []
        
        # Local branches
        for branch in self.repo.branches:
            branches.append({
                "name": branch.name,
                "is_remote": False,
                "commit_sha": branch.commit.hexsha[:7],
                "is_current": branch.name == self.get_current_branch()
            })
        
        # Remote branches
        if include_remote:
            for ref in self.repo.remotes.origin.refs:
                remote_name = ref.name.replace("origin/", "")
                if remote_name != "HEAD":
                    branches.append({
                        "name": remote_name,
                        "is_remote": True,
                        "commit_sha": ref.commit.hexsha[:7],
                        "is_current": False
                    })
        
        return branches
    
    def checkout_branch(self, branch_name: str, create: bool = False) -> bool:
        """
        Checkout to a specific branch
        
        Args:
            branch_name: Name of the branch
            create: Create branch if it doesn't exist
        """
        if not self.repo:
            return False
        
        try:
            if create and branch_name not in [b.name for b in self.repo.branches]:
                self.repo.create_head(branch_name)
            
            self.repo.git.checkout(branch_name)
            return True
        except GitCommandError:
            return False
    
    def fetch_all(self) -> bool:
        """Fetch all remotes"""
        if not self.repo:
            return False
        try:
            for remote in self.repo.remotes:
                remote.fetch()
            return True
        except GitCommandError:
            return False
    
    def pull(self, branch: str = None) -> bool:
        """Pull changes from remote"""
        if not self.repo:
            return False
        try:
            self.repo.remotes.origin.pull(branch or self.get_current_branch())
            return True
        except GitCommandError:
            return False
    
    def get_commit_history(
        self,
        branch: str = None,
        limit: int = 50,
        skip: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get commit history for a branch
        
        Args:
            branch: Branch name (defaults to current branch)
            limit: Maximum number of commits to return
            skip: Number of commits to skip (for pagination)
        
        Returns:
            List of commit dictionaries
        """
        if not self.repo:
            return []
        
        try:
            # Get commits iterator
            commits_iter = self.repo.iter_commits(
                branch or self.get_current_branch(),
                max_count=limit,
                skip=skip
            )
            
            commits = []
            for commit in commits_iter:
                commits.append({
                    "sha": commit.hexsha,
                    "short_sha": commit.hexsha[:7],
                    "message": commit.message.strip(),
                    "author_name": commit.author.name,
                    "author_email": commit.author.email,
                    "committed_at": datetime.fromtimestamp(commit.committed_date).isoformat() + "Z",
                    "parent_sha": commit.parents[0].hexsha if commit.parents else None,
                })
            
            return commits
        except Exception:
            return []
    
    def get_commit_diff(self, commit_sha: str) -> Dict[str, Any]:
        """
        Get detailed diff information for a specific commit
        
        Returns the structured format:
        {
            "commit": { ... },
            "summary": { total_files_changed, total_lines_added, total_lines_removed },
            "files": [ { file_path, change_type, language, lines_added, lines_removed, line_changes } ]
        }
        """
        if not self.repo:
            return None
        
        try:
            commit = self.repo.commit(commit_sha)
            parent = commit.parents[0] if commit.parents else None
            
            # Get diff
            if parent:
                diffs = parent.diff(commit, create_patch=True)
            else:
                # Initial commit - diff against empty tree
                diffs = commit.diff(None, create_patch=True)
            
            files = []
            total_added = 0
            total_removed = 0
            
            for diff in diffs:
                file_info = self._parse_diff_item(diff)
                files.append(file_info)
                total_added += file_info["lines_added"]
                total_removed += file_info["lines_removed"]
            
            return {
                "commit": {
                    "id": commit.hexsha,
                    "short_sha": commit.hexsha[:7],
                    "branch": self.get_current_branch(),
                    "author": commit.author.name,
                    "email": commit.author.email,
                    "message": commit.message.strip(),
                    "timestamp": datetime.fromtimestamp(commit.committed_date).isoformat() + "Z"
                },
                "summary": {
                    "total_files_changed": len(files),
                    "total_lines_added": total_added,
                    "total_lines_removed": total_removed
                },
                "files": files,
                "cached": False
            }
        except Exception as e:
            return {"error": str(e)}
    
    def _parse_diff_item(self, diff) -> Dict[str, Any]:
        """Parse a single diff item into structured format"""
        # Determine change type
        if diff.new_file:
            change_type = "added"
            file_path = diff.b_path
            old_path = None
        elif diff.deleted_file:
            change_type = "deleted"
            file_path = diff.a_path
            old_path = None
        elif diff.renamed_file:
            change_type = "renamed"
            file_path = diff.b_path
            old_path = diff.a_path
        else:
            change_type = "modified"
            file_path = diff.b_path or diff.a_path
            old_path = None
        
        # Parse the patch to get line-level changes
        lines_added = 0
        lines_removed = 0
        line_changes = []
        
        try:
            if diff.diff:
                patch = diff.diff.decode('utf-8', errors='replace')
                lines_added, lines_removed, line_changes = self._parse_patch(patch)
        except Exception:
            pass
        
        return {
            "file_path": file_path,
            "old_file_path": old_path,
            "change_type": change_type,
            "language": detect_language(file_path),
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "line_changes": line_changes
        }
    
    def _parse_patch(self, patch: str) -> tuple:
        """
        Parse a unified diff patch to extract line-level changes
        
        Returns:
            (lines_added, lines_removed, line_changes)
        """
        lines_added = 0
        lines_removed = 0
        line_changes = []
        
        # Track current line numbers
        old_line = 0
        new_line = 0
        
        # Regex to match hunk headers: @@ -start,count +start,count @@
        hunk_pattern = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')
        
        for line in patch.split('\n'):
            # Skip diff metadata lines
            if line.startswith('diff --git') or line.startswith('index ') or \
               line.startswith('---') or line.startswith('+++'):
                continue
            
            # Parse hunk header
            hunk_match = hunk_pattern.match(line)
            if hunk_match:
                old_line = int(hunk_match.group(1))
                new_line = int(hunk_match.group(2))
                continue
            
            # Parse actual changes
            if line.startswith('+') and not line.startswith('+++'):
                lines_added += 1
                line_changes.append({
                    "old_line": None,
                    "new_line": new_line,
                    "change_type": "added",
                    "code": line[1:]  # Remove the + prefix
                })
                new_line += 1
            elif line.startswith('-') and not line.startswith('---'):
                lines_removed += 1
                line_changes.append({
                    "old_line": old_line,
                    "new_line": None,
                    "change_type": "removed",
                    "code": line[1:]  # Remove the - prefix
                })
                old_line += 1
            elif line.startswith(' '):
                # Context line (unchanged)
                old_line += 1
                new_line += 1
        
        return lines_added, lines_removed, line_changes
    
    def get_uncommitted_changes(self) -> Dict[str, Any]:
        """
        Get uncommitted changes in the working directory
        
        Returns diff between HEAD and working directory
        """
        if not self.repo:
            return None
        
        try:
            # Get staged changes
            staged_diffs = self.repo.index.diff(self.repo.head.commit, create_patch=True)
            
            # Get unstaged changes
            unstaged_diffs = self.repo.index.diff(None, create_patch=True)
            
            # Get untracked files
            untracked = self.repo.untracked_files
            
            staged_files = []
            unstaged_files = []
            total_added = 0
            total_removed = 0
            
            for diff in staged_diffs:
                file_info = self._parse_diff_item(diff)
                file_info["staged"] = True
                staged_files.append(file_info)
                total_added += file_info["lines_added"]
                total_removed += file_info["lines_removed"]
            
            for diff in unstaged_diffs:
                file_info = self._parse_diff_item(diff)
                file_info["staged"] = False
                unstaged_files.append(file_info)
                total_added += file_info["lines_added"]
                total_removed += file_info["lines_removed"]
            
            return {
                "summary": {
                    "total_staged": len(staged_files),
                    "total_unstaged": len(unstaged_files),
                    "total_untracked": len(untracked),
                    "total_lines_added": total_added,
                    "total_lines_removed": total_removed
                },
                "staged_files": staged_files,
                "unstaged_files": unstaged_files,
                "untracked_files": [{"file_path": f, "change_type": "untracked"} for f in untracked]
            }
        except Exception as e:
            return {"error": str(e)}
    
    def compare_commits(self, from_sha: str, to_sha: str) -> Dict[str, Any]:
        """
        Compare two commits and return the diff between them
        
        Args:
            from_sha: Starting commit SHA
            to_sha: Ending commit SHA
        
        Returns:
            Diff information between the two commits
        """
        if not self.repo:
            return None
        
        try:
            from_commit = self.repo.commit(from_sha)
            to_commit = self.repo.commit(to_sha)
            
            diffs = from_commit.diff(to_commit, create_patch=True)
            
            files = []
            total_added = 0
            total_removed = 0
            
            for diff in diffs:
                file_info = self._parse_diff_item(diff)
                files.append(file_info)
                total_added += file_info["lines_added"]
                total_removed += file_info["lines_removed"]
            
            return {
                "comparison": {
                    "from_commit": from_sha[:7],
                    "to_commit": to_sha[:7],
                    "from_message": from_commit.message.strip().split('\n')[0],
                    "to_message": to_commit.message.strip().split('\n')[0],
                },
                "summary": {
                    "total_files_changed": len(files),
                    "total_lines_added": total_added,
                    "total_lines_removed": total_removed
                },
                "files": files
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_file_content(self, file_path: str, commit_sha: str = None) -> Optional[str]:
        """
        Get file content at a specific commit or current HEAD
        
        Args:
            file_path: Path to the file relative to repo root
            commit_sha: Commit SHA (defaults to HEAD)
        """
        if not self.repo:
            return None
        
        try:
            if commit_sha:
                commit = self.repo.commit(commit_sha)
            else:
                commit = self.repo.head.commit
            
            blob = commit.tree / file_path
            return blob.data_stream.read().decode('utf-8', errors='replace')
        except Exception:
            return None
    
    def get_file_tree(self, commit_sha: str = None, path: str = "") -> List[Dict[str, Any]]:
        """
        Get file tree structure at a specific commit
        
        Args:
            commit_sha: Commit SHA (defaults to HEAD)
            path: Subdirectory path to list
        
        Returns:
            List of files and directories
        """
        if not self.repo:
            return []
        
        try:
            if commit_sha:
                commit = self.repo.commit(commit_sha)
            else:
                commit = self.repo.head.commit
            
            tree = commit.tree
            
            # Navigate to subdirectory if path provided
            if path:
                for part in path.split('/'):
                    if part:
                        tree = tree / part
            
            items = []
            for item in tree:
                items.append({
                    "name": item.name,
                    "path": item.path,
                    "type": "directory" if item.type == "tree" else "file",
                    "size": item.size if item.type == "blob" else None,
                    "language": detect_language(item.name) if item.type == "blob" else None
                })
            
            return sorted(items, key=lambda x: (x["type"] != "directory", x["name"].lower()))
        except Exception:
            return []
