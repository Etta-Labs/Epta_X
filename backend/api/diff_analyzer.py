"""
Git Diff and AST Analysis Module for ETTA-X
Performs incremental code analysis on changed files.

Features:
- Git diff processing to extract changed files and line ranges
- AST parsing for Python source files
- Change classification (API, service, UI, config)
- Deterministic, explainable analysis with no AI/ML

Author: ETTA-X
"""

import ast
import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Set, Tuple
from pathlib import Path


class ChangeType(Enum):
    """Classification of code changes"""
    API = "api_change"
    SERVICE = "service_change"
    UI = "ui_change"
    CONFIG = "config_change"
    TEST = "test_change"
    DOCS = "docs_change"
    UNKNOWN = "unknown_change"


@dataclass
class LineRange:
    """Represents a range of lines that were modified"""
    start: int
    end: int
    change_type: str  # 'added', 'removed', 'modified'
    
    def contains(self, line: int) -> bool:
        """Check if a line number falls within this range"""
        return self.start <= line <= self.end
    
    def overlaps(self, other_start: int, other_end: int) -> bool:
        """Check if this range overlaps with another range"""
        return not (self.end < other_start or self.start > other_end)


@dataclass
class ASTNode:
    """Represents an extracted AST node"""
    name: str
    node_type: str  # 'function', 'class', 'decorator', 'import'
    start_line: int
    end_line: int
    parent: Optional[str] = None  # Parent class/function name if nested
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    is_async: bool = False
    parameters: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.node_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "parent": self.parent,
            "decorators": self.decorators,
            "docstring": self.docstring,
            "is_async": self.is_async,
            "parameters": self.parameters
        }


@dataclass
class ChangedFile:
    """Represents a file that was changed in the diff"""
    path: str
    status: str  # 'added', 'modified', 'deleted', 'renamed'
    old_path: Optional[str] = None  # For renamed files
    line_ranges: List[LineRange] = field(default_factory=list)
    ast_nodes: List[ASTNode] = field(default_factory=list)
    changed_nodes: List[ASTNode] = field(default_factory=list)
    change_types: Set[ChangeType] = field(default_factory=set)
    diff: str = ""  # Raw diff text for this file
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "old_path": self.old_path,
            "line_ranges": [
                {"start": r.start, "end": r.end, "type": r.change_type}
                for r in self.line_ranges
            ],
            "changed_nodes": [n.to_dict() for n in self.changed_nodes],
            "change_types": [ct.value for ct in self.change_types],
            "diff": self.diff
        }


@dataclass
class DiffAnalysisResult:
    """Complete result of diff analysis"""
    old_commit: str
    new_commit: str
    changed_files: List[ChangedFile]
    changed_functions: List[Dict[str, Any]]
    change_types: List[str]
    affected_components: List[str]
    summary: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "old_commit": self.old_commit,
            "new_commit": self.new_commit,
            "changed_files": [f.to_dict() for f in self.changed_files],
            "changed_functions": self.changed_functions,
            "change_types": self.change_types,
            "affected_components": self.affected_components,
            "summary": self.summary
        }


class FileFilter:
    """Filters files to ignore non-source files"""
    
    # File extensions to analyze
    SOURCE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs',
        '.c', '.cpp', '.h', '.hpp', '.cs', '.rb', '.php',
        '.html', '.htm', '.css', '.scss', '.sass', '.less', '.vue', '.svelte'
    }
    
    # Config file extensions
    CONFIG_EXTENSIONS = {
        '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
        '.env', '.properties'
    }
    
    # Files/patterns to always ignore
    IGNORE_PATTERNS = [
        r'\.git/',
        r'\.gitignore$',
        r'node_modules/',
        r'__pycache__/',
        r'\.pyc$',
        r'\.pyo$',
        r'venv/',
        r'\.venv/',
        r'dist/',
        r'build/',
        r'\.egg-info/',
        r'\.min\.js$',
        r'\.min\.css$',
        r'package-lock\.json$',
        r'yarn\.lock$',
        r'poetry\.lock$',
        r'\.map$',  # Source maps
    ]
    
    # Binary/non-source extensions to ignore
    IGNORE_EXTENSIONS = {
        '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp',
        '.mp3', '.mp4', '.wav', '.avi', '.mov',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx',
        '.zip', '.tar', '.gz', '.rar', '.7z',
        '.exe', '.dll', '.so', '.dylib',
        '.ttf', '.woff', '.woff2', '.eot',
        '.db', '.sqlite', '.sqlite3',
        '.pyc', '.pyo', '.class',
        '.o', '.obj', '.a', '.lib',
    }
    
    # Documentation patterns
    DOCS_PATTERNS = [
        r'README',
        r'CHANGELOG',
        r'LICENSE',
        r'CONTRIBUTING',
        r'docs/',
        r'documentation/',
        r'\.md$',
        r'\.rst$',
        r'\.txt$',
    ]
    
    @classmethod
    def should_analyze(cls, file_path: str) -> bool:
        """Determine if a file should be analyzed"""
        path_lower = file_path.lower()
        
        # Check ignore patterns
        for pattern in cls.IGNORE_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return False
        
        # Check extension
        ext = os.path.splitext(path_lower)[1]
        if ext in cls.IGNORE_EXTENSIONS:
            return False
        
        # Accept source and config files
        if ext in cls.SOURCE_EXTENSIONS or ext in cls.CONFIG_EXTENSIONS:
            return True
        
        return False
    
    @classmethod
    def get_file_category(cls, file_path: str) -> str:
        """Categorize a file based on its path and extension"""
        path_lower = file_path.lower()
        ext = os.path.splitext(path_lower)[1]
        
        # Check for documentation
        for pattern in cls.DOCS_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return "docs"
        
        # Check for tests
        if '/test' in path_lower or 'test_' in path_lower or '_test.' in path_lower:
            return "test"
        
        # Check for config files
        if ext in cls.CONFIG_EXTENSIONS:
            return "config"
        
        # Check for UI files
        if ext in {'.jsx', '.tsx', '.vue', '.svelte'}:
            return "ui"
        if '/components/' in path_lower or '/pages/' in path_lower or '/views/' in path_lower:
            return "ui"
        if ext == '.css' or ext == '.scss' or ext == '.less':
            return "ui"
        if ext == '.html':
            return "ui"
        
        # Check for API files
        if '/api/' in path_lower or '/routes/' in path_lower or '/endpoints/' in path_lower:
            return "api"
        
        # Default to service/business logic
        return "service"


class GitDiffParser:
    """Parses git diff output to extract changed files and line ranges"""
    
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
    
    def get_diff(self, old_commit: str, new_commit: str) -> str:
        """Get git diff between two commits"""
        try:
            result = subprocess.run(
                ['git', 'diff', '--unified=0', old_commit, new_commit],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                raise Exception(f"Git diff failed: {result.stderr}")
            return result.stdout
        except subprocess.TimeoutExpired:
            raise Exception("Git diff timed out")
    
    def get_changed_files_list(self, old_commit: str, new_commit: str) -> List[Tuple[str, str, Optional[str]]]:
        """Get list of changed files with their status"""
        try:
            result = subprocess.run(
                ['git', 'diff', '--name-status', old_commit, new_commit],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                raise Exception(f"Git diff failed: {result.stderr}")
            
            files = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split('\t')
                status_code = parts[0][0]  # First character (M, A, D, R, etc.)
                
                status_map = {
                    'A': 'added',
                    'M': 'modified',
                    'D': 'deleted',
                    'R': 'renamed',
                    'C': 'copied',
                }
                status = status_map.get(status_code, 'modified')
                
                if status == 'renamed' and len(parts) >= 3:
                    old_path = parts[1]
                    new_path = parts[2]
                    files.append((new_path, status, old_path))
                else:
                    files.append((parts[1] if len(parts) > 1 else parts[0], status, None))
            
            return files
        except subprocess.TimeoutExpired:
            raise Exception("Git diff timed out")
    
    def parse_diff(self, old_commit: str, new_commit: str) -> List[ChangedFile]:
        """Parse complete diff and extract file changes with line ranges"""
        # Get list of changed files
        file_list = self.get_changed_files_list(old_commit, new_commit)
        
        # Get detailed diff (with context for display)
        try:
            result = subprocess.run(
                ['git', 'diff', '--unified=3', old_commit, new_commit],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            diff_output_with_context = result.stdout if result.returncode == 0 else ""
        except:
            diff_output_with_context = ""
        
        # Also get the minimal diff for line range parsing
        diff_output = self.get_diff(old_commit, new_commit)
        
        # Parse diff output
        changed_files = {}
        current_file = None
        
        for path, status, old_path in file_list:
            if FileFilter.should_analyze(path):
                changed_files[path] = ChangedFile(
                    path=path,
                    status=status,
                    old_path=old_path
                )
        
        # Parse per-file diffs from the context diff
        current_file_path = None
        current_file_diff = []
        
        for line in diff_output_with_context.split('\n'):
            # Match file header: diff --git a/path b/path
            file_match = re.match(r'^diff --git a/(.+) b/(.+)$', line)
            if file_match:
                # Save previous file's diff
                if current_file_path and current_file_path in changed_files:
                    changed_files[current_file_path].diff = '\n'.join(current_file_diff)
                
                current_file_path = file_match.group(2)
                current_file_diff = [line]
                continue
            
            # Accumulate diff lines for current file
            if current_file_path:
                current_file_diff.append(line)
        
        # Don't forget the last file
        if current_file_path and current_file_path in changed_files:
            changed_files[current_file_path].diff = '\n'.join(current_file_diff)
        
        # Parse hunks from minimal diff output for line ranges
        current_file_path = None
        
        for line in diff_output.split('\n'):
            # Match file header: diff --git a/path b/path
            file_match = re.match(r'^diff --git a/(.+) b/(.+)$', line)
            if file_match:
                current_file_path = file_match.group(2)
                continue
            
            # Match hunk header: @@ -old_start,old_count +new_start,new_count @@
            hunk_match = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
            if hunk_match and current_file_path and current_file_path in changed_files:
                old_start = int(hunk_match.group(1))
                old_count = int(hunk_match.group(2) or 1)
                new_start = int(hunk_match.group(3))
                new_count = int(hunk_match.group(4) or 1)
                
                # Determine change type
                if old_count == 0:
                    change_type = 'added'
                elif new_count == 0:
                    change_type = 'removed'
                else:
                    change_type = 'modified'
                
                # Use new file line numbers for analysis
                if new_count > 0:
                    changed_files[current_file_path].line_ranges.append(
                        LineRange(new_start, new_start + new_count - 1, change_type)
                    )
        
        return list(changed_files.values())
    
    def get_file_content(self, commit: str, file_path: str) -> Optional[str]:
        """Get file content at a specific commit"""
        try:
            result = subprocess.run(
                ['git', 'show', f'{commit}:{file_path}'],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout
            return None
        except:
            return None


class PythonASTAnalyzer:
    """Analyzes Python source code using AST"""
    
    # Decorators that indicate API routes
    API_DECORATORS = {
        'route', 'get', 'post', 'put', 'delete', 'patch', 'head', 'options',
        'app.route', 'app.get', 'app.post', 'app.put', 'app.delete',
        'router.get', 'router.post', 'router.put', 'router.delete',
        'api_view', 'action', 'endpoint',
        'blueprint.route', 'bp.route',
    }
    
    # Decorators that indicate service/business logic
    SERVICE_DECORATORS = {
        'celery.task', 'task', 'background_task', 'job',
        'cached', 'cache', 'memoize',
        'transaction', 'atomic',
        'retry', 'backoff',
    }
    
    def __init__(self, source_code: str, file_path: str = ""):
        self.source_code = source_code
        self.file_path = file_path
        self.tree = None
        self.nodes: List[ASTNode] = []
        self.imports: List[ASTNode] = []
    
    def parse(self) -> bool:
        """Parse the source code into an AST"""
        try:
            self.tree = ast.parse(self.source_code)
            return True
        except SyntaxError as e:
            print(f"Syntax error in {self.file_path}: {e}")
            return False
    
    def extract_nodes(self) -> List[ASTNode]:
        """Extract all relevant AST nodes"""
        if not self.tree:
            if not self.parse():
                return []
        
        self.nodes = []
        self.imports = []
        self._visit_node(self.tree, parent=None)
        
        return self.nodes
    
    def _get_decorator_names(self, decorators: list) -> List[str]:
        """Extract decorator names from a list of decorator nodes"""
        names = []
        for dec in decorators:
            if isinstance(dec, ast.Name):
                names.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                names.append(self._get_full_attribute_name(dec))
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    names.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    names.append(self._get_full_attribute_name(dec.func))
        return names
    
    def _get_full_attribute_name(self, node: ast.Attribute) -> str:
        """Get full dotted name from attribute node"""
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return '.'.join(reversed(parts))
    
    def _get_docstring(self, node) -> Optional[str]:
        """Extract docstring from a node"""
        try:
            docstring = ast.get_docstring(node)
            if docstring:
                # Truncate long docstrings
                return docstring[:200] + "..." if len(docstring) > 200 else docstring
            return None
        except:
            return None
    
    def _get_parameters(self, node) -> List[str]:
        """Extract parameter names from function definition"""
        params = []
        if hasattr(node, 'args'):
            args = node.args
            # Regular args
            for arg in args.args:
                params.append(arg.arg)
            # *args
            if args.vararg:
                params.append(f"*{args.vararg.arg}")
            # Keyword-only args
            for arg in args.kwonlyargs:
                params.append(arg.arg)
            # **kwargs
            if args.kwarg:
                params.append(f"**{args.kwarg.arg}")
        return params
    
    def _visit_node(self, node, parent: Optional[str] = None):
        """Recursively visit AST nodes"""
        
        # Handle imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                self.imports.append(ASTNode(
                    name=alias.name,
                    node_type='import',
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno
                ))
                self.nodes.append(self.imports[-1])
        
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                import_name = f"{module}.{alias.name}" if module else alias.name
                self.imports.append(ASTNode(
                    name=import_name,
                    node_type='import',
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno
                ))
                self.nodes.append(self.imports[-1])
        
        # Handle class definitions
        elif isinstance(node, ast.ClassDef):
            decorators = self._get_decorator_names(node.decorator_list)
            ast_node = ASTNode(
                name=node.name,
                node_type='class',
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parent=parent,
                decorators=decorators,
                docstring=self._get_docstring(node)
            )
            self.nodes.append(ast_node)
            
            # Visit class body with class as parent
            for child in ast.iter_child_nodes(node):
                self._visit_node(child, parent=node.name)
        
        # Handle function definitions
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = self._get_decorator_names(node.decorator_list)
            ast_node = ASTNode(
                name=node.name,
                node_type='function',
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parent=parent,
                decorators=decorators,
                docstring=self._get_docstring(node),
                is_async=isinstance(node, ast.AsyncFunctionDef),
                parameters=self._get_parameters(node)
            )
            self.nodes.append(ast_node)
            
            # Visit function body (for nested functions)
            for child in ast.iter_child_nodes(node):
                self._visit_node(child, parent=node.name)
        
        # Continue traversing for other nodes
        else:
            for child in ast.iter_child_nodes(node):
                self._visit_node(child, parent=parent)
    
    def classify_node(self, node: ASTNode) -> Set[ChangeType]:
        """Classify a node based on its characteristics"""
        types = set()
        
        # Check decorators for API indicators
        for dec in node.decorators:
            dec_lower = dec.lower()
            if any(api_dec in dec_lower for api_dec in self.API_DECORATORS):
                types.add(ChangeType.API)
            if any(svc_dec in dec_lower for svc_dec in self.SERVICE_DECORATORS):
                types.add(ChangeType.SERVICE)
        
        # Check function/class name patterns
        name_lower = node.name.lower()
        
        # Test patterns
        if name_lower.startswith('test_') or name_lower.endswith('_test'):
            types.add(ChangeType.TEST)
        
        # API patterns in name
        if any(p in name_lower for p in ['_handler', '_endpoint', '_route', '_view', '_api']):
            types.add(ChangeType.API)
        
        # UI patterns
        if any(p in name_lower for p in ['_component', '_widget', '_render', '_display']):
            types.add(ChangeType.UI)
        
        # Service patterns
        if any(p in name_lower for p in ['_service', '_manager', '_processor', '_worker']):
            types.add(ChangeType.SERVICE)
        
        # If no specific type detected, default to SERVICE
        if not types:
            types.add(ChangeType.SERVICE)
        
        return types


class ChangeClassifier:
    """Classifies changes based on file path and content analysis"""
    
    @staticmethod
    def classify_file(file: ChangedFile, ast_analyzer: Optional[PythonASTAnalyzer] = None) -> Set[ChangeType]:
        """Classify a file's changes"""
        types = set()
        
        # Get category from file path
        category = FileFilter.get_file_category(file.path)
        category_map = {
            'api': ChangeType.API,
            'service': ChangeType.SERVICE,
            'ui': ChangeType.UI,
            'config': ChangeType.CONFIG,
            'test': ChangeType.TEST,
            'docs': ChangeType.DOCS,
        }
        types.add(category_map.get(category, ChangeType.SERVICE))
        
        # Add types from changed nodes
        for node in file.changed_nodes:
            if ast_analyzer:
                types.update(ast_analyzer.classify_node(node))
        
        return types
    
    @staticmethod
    def get_affected_components(files: List[ChangedFile]) -> List[str]:
        """Extract affected components from changed files"""
        components = set()
        
        for file in files:
            path_parts = Path(file.path).parts
            
            # Extract meaningful component names
            for part in path_parts:
                if part in {'src', 'lib', 'app', 'backend', 'frontend', 'api', 'core'}:
                    continue
                if part.startswith('.') or part.startswith('__'):
                    continue
                if os.path.splitext(part)[1]:  # Skip file names
                    continue
                components.add(part)
            
            # Add parent folder of files as component
            if len(path_parts) > 1:
                components.add(path_parts[-2] if len(path_parts) > 1 else path_parts[0])
            
            # Add changed classes/functions as components
            for node in file.changed_nodes:
                if node.node_type == 'class':
                    components.add(node.name)
                elif node.node_type == 'function' and node.parent:
                    components.add(f"{node.parent}.{node.name}")
        
        return sorted(list(components))


class DiffAnalyzer:
    """Main class for analyzing git diffs"""
    
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.git_parser = GitDiffParser(repo_path)
    
    def analyze(self, old_commit: str, new_commit: str) -> DiffAnalysisResult:
        """
        Perform complete diff analysis between two commits.
        
        Args:
            old_commit: SHA of the older commit
            new_commit: SHA of the newer commit
        
        Returns:
            DiffAnalysisResult containing all analysis data
        """
        # Parse git diff
        changed_files = self.git_parser.parse_diff(old_commit, new_commit)
        
        all_change_types = set()
        all_changed_functions = []
        
        # Analyze each changed file
        for file in changed_files:
            # Skip deleted files (can't analyze content)
            if file.status == 'deleted':
                file.change_types.add(ChangeType.UNKNOWN)
                continue
            
            # Get file extension
            ext = os.path.splitext(file.path)[1].lower()
            
            # Analyze Python files with AST
            if ext == '.py':
                content = self.git_parser.get_file_content(new_commit, file.path)
                if content:
                    ast_analyzer = PythonASTAnalyzer(content, file.path)
                    nodes = ast_analyzer.extract_nodes()
                    file.ast_nodes = nodes
                    
                    # Map changed lines to AST nodes
                    for node in nodes:
                        for line_range in file.line_ranges:
                            if line_range.overlaps(node.start_line, node.end_line):
                                file.changed_nodes.append(node)
                                
                                # Add to changed functions list
                                if node.node_type in ('function', 'class'):
                                    func_info = node.to_dict()
                                    func_info['file'] = file.path
                                    func_info['change_type'] = line_range.change_type
                                    all_changed_functions.append(func_info)
                                break
                    
                    # Classify changes
                    file.change_types = ChangeClassifier.classify_file(file, ast_analyzer)
            else:
                # For non-Python files, classify based on file path
                file.change_types = ChangeClassifier.classify_file(file)
            
            all_change_types.update(file.change_types)
        
        # Get affected components
        affected_components = ChangeClassifier.get_affected_components(changed_files)
        
        # Build summary
        summary = {
            "total_files": len(changed_files),
            "added_files": sum(1 for f in changed_files if f.status == 'added'),
            "modified_files": sum(1 for f in changed_files if f.status == 'modified'),
            "deleted_files": sum(1 for f in changed_files if f.status == 'deleted'),
            "total_functions_changed": len(all_changed_functions),
            "change_type_counts": {
                ct.value: sum(1 for f in changed_files if ct in f.change_types)
                for ct in ChangeType
                if any(ct in f.change_types for f in changed_files)
            }
        }
        
        return DiffAnalysisResult(
            old_commit=old_commit,
            new_commit=new_commit,
            changed_files=changed_files,
            changed_functions=all_changed_functions,
            change_types=sorted([ct.value for ct in all_change_types]),
            affected_components=affected_components,
            summary=summary
        )
    
    def analyze_webhook_event(self, event_data: Dict[str, Any]) -> Optional[DiffAnalysisResult]:
        """
        Analyze changes from a webhook event.
        
        Args:
            event_data: Parsed webhook event data (from WebhookPayloadParser)
        
        Returns:
            DiffAnalysisResult or None if analysis not applicable
        """
        event_type = event_data.get('event_type')
        
        if event_type == 'push':
            before = event_data.get('before')
            after = event_data.get('after')
            
            if before and after and before != '0' * 40:  # Not a new branch
                return self.analyze(before, after)
        
        elif event_type == 'pull_request':
            pr_data = event_data.get('pull_request', {})
            base_sha = pr_data.get('base', {}).get('sha')
            head_sha = pr_data.get('head', {}).get('sha')
            
            if base_sha and head_sha:
                return self.analyze(base_sha, head_sha)
        
        return None


# Utility functions for integration with app.py

def analyze_commits(repo_path: str, old_commit: str, new_commit: str) -> Dict[str, Any]:
    """
    Convenience function to analyze commits and return JSON-serializable result.
    
    Args:
        repo_path: Path to the git repository
        old_commit: SHA of the older commit
        new_commit: SHA of the newer commit
    
    Returns:
        Dictionary with analysis results
    """
    analyzer = DiffAnalyzer(repo_path)
    result = analyzer.analyze(old_commit, new_commit)
    return result.to_dict()


def analyze_from_webhook(repo_path: str, webhook_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Analyze changes from a webhook payload.
    
    Args:
        repo_path: Path to the git repository
        webhook_payload: Parsed webhook payload
    
    Returns:
        Dictionary with analysis results or None
    """
    analyzer = DiffAnalyzer(repo_path)
    result = analyzer.analyze_webhook_event(webhook_payload)
    return result.to_dict() if result else None
