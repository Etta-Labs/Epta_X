"""
Test Generator Module
=====================
Uses the local LLM to generate test cases from code descriptions.

Usage:
    from backend.model.LLM.test_generator import generate_tests
    
    tests = generate_tests(
        code_description="POST /login accepts username and password...",
        language="python"
    )
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

from .local_model import get_llm_instance
from .config import SYSTEM_PROMPT, TEST_GENERATION_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """Represents a generated test case."""
    name: str
    endpoint: str
    method: str
    payload: Dict[str, Any]
    expected_status: int
    description: str = ""
    priority_score: float = 0.0
    category: str = "functional"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass 
class TestGenerationResult:
    """Result of test generation."""
    success: bool
    tests: List[TestCase]
    raw_response: str
    error: Optional[str] = None
    generation_time_ms: float = 0.0
    model_used: str = "CodeLlama-7B-Instruct"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tests": [t.to_dict() for t in self.tests],
            "test_count": len(self.tests),
            "error": self.error,
            "generation_time_ms": self.generation_time_ms,
            "model_used": self.model_used,
            "generated_at": datetime.now().isoformat()
        }


class TestGenerator:
    """
    Generates test cases using the local LLM.
    
    Features:
    - Structured prompt engineering for consistent output
    - JSON parsing with fallback strategies
    - Test case validation and normalization
    - Category detection for prioritization
    """
    
    def __init__(self):
        self.llm = get_llm_instance()
        
    def _build_prompt(self, code_description: str, language: str = "python") -> str:
        """Build the full prompt for test generation."""
        return TEST_GENERATION_PROMPT_TEMPLATE.format(
            code_description=code_description,
            language=language
        )
    
    def _parse_response(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse LLM response to extract test cases.
        Tries multiple strategies for robustness.
        """
        logger.debug(f"Parsing LLM response ({len(response)} chars): {response[:200]}...")
        
        # Clean up response first
        cleaned = response.strip()
        
        # Remove markdown code blocks
        cleaned = re.sub(r'```json\s*', '', cleaned)
        cleaned = re.sub(r'```python\s*', '', cleaned)
        cleaned = re.sub(r'```\s*', '', cleaned)
        cleaned = cleaned.strip()
        
        # Strategy 1: Direct JSON parse
        try:
            data = json.loads(cleaned)
            tests = self._extract_tests_from_data(data)
            if tests:
                return tests
        except json.JSONDecodeError as e:
            logger.debug(f"Direct parse failed: {e}")
        
        # Strategy 2: Find JSON object with tests key
        match = re.search(r'\{\s*"tests"\s*:\s*\[', cleaned)
        if match:
            # Try to find matching closing bracket
            start = match.start()
            try:
                # Parse from the start of the JSON object
                data = json.loads(cleaned[start:])
                tests = self._extract_tests_from_data(data)
                if tests:
                    return tests
            except json.JSONDecodeError:
                # Try to find the end manually
                bracket_count = 0
                in_string = False
                escape_next = False
                for i, char in enumerate(cleaned[start:]):
                    if escape_next:
                        escape_next = False
                        continue
                    if char == '\\':
                        escape_next = True
                        continue
                    if char == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if not in_string:
                        if char == '{':
                            bracket_count += 1
                        elif char == '}':
                            bracket_count -= 1
                            if bracket_count == 0:
                                try:
                                    data = json.loads(cleaned[start:start+i+1])
                                    tests = self._extract_tests_from_data(data)
                                    if tests:
                                        return tests
                                except json.JSONDecodeError:
                                    pass
                                break
        
        # Strategy 3: Find just a JSON array
        array_match = re.search(r'\[\s*\{', cleaned)
        if array_match:
            start = array_match.start()
            try:
                data = json.loads(cleaned[start:])
                tests = self._extract_tests_from_data(data)
                if tests:
                    return tests
            except json.JSONDecodeError:
                pass
        
        # Strategy 4: Extract individual test objects
        test_objects = []
        for match in re.finditer(r'\{[^{}]*"name"[^{}]*"endpoint"[^{}]*\}', cleaned):
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict) and 'name' in obj:
                    test_objects.append(obj)
            except json.JSONDecodeError:
                continue
        
        if test_objects:
            return test_objects
        
        logger.error(f"Failed to parse test cases from response: {response[:500]}")
        return []
    
    def _extract_tests_from_data(self, data: Any) -> List[Dict[str, Any]]:
        """Extract test cases from parsed JSON data."""
        if isinstance(data, dict):
            if "tests" in data:
                tests = data["tests"]
                if isinstance(tests, list):
                    # Filter to only include dict items
                    return [t for t in tests if isinstance(t, dict)]
            # Maybe the dict itself is a test
            if "name" in data or "endpoint" in data:
                return [data]
        elif isinstance(data, list):
            # Filter to only include dict items
            result = []
            for item in data:
                if isinstance(item, dict):
                    result.append(item)
                elif isinstance(item, str):
                    # Try to parse string as JSON
                    try:
                        parsed = json.loads(item)
                        if isinstance(parsed, dict):
                            result.append(parsed)
                    except json.JSONDecodeError:
                        pass
            return result
        return []
    
    def _normalize_test(self, test_data: Any, index: int) -> TestCase:
        """Normalize and validate a test case."""
        # Handle case where test_data is not a dict
        if not isinstance(test_data, dict):
            logger.warning(f"Test data {index} is {type(test_data).__name__}, not dict: {str(test_data)[:100]}")
            raise ValueError(f"Test data must be a dict, got {type(test_data).__name__}")
        
        # Ensure required fields with defaults
        name = test_data.get("name", f"test_case_{index}")
        
        # Normalize test name to snake_case
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name.lower())
        if not name.startswith("test_"):
            name = f"test_{name}"
        
        endpoint = test_data.get("endpoint", "/")
        method = test_data.get("method", "GET").upper()
        payload = test_data.get("payload", {})
        expected_status = int(test_data.get("expected_status", 200))
        description = test_data.get("description", "")
        
        # Detect category based on test characteristics
        category = self._detect_category(name, endpoint, expected_status)
        
        return TestCase(
            name=name,
            endpoint=endpoint,
            method=method,
            payload=payload if isinstance(payload, dict) else {},
            expected_status=expected_status,
            description=description,
            category=category
        )
    
    def _detect_category(self, name: str, endpoint: str, status: int) -> str:
        """Detect test category for prioritization."""
        name_lower = name.lower()
        endpoint_lower = endpoint.lower()
        
        # Authentication tests - highest priority
        if any(x in name_lower or x in endpoint_lower for x in ['auth', 'login', 'logout', 'token', 'session']):
            return "authentication"
        
        # Error handling tests
        if status >= 400:
            return "error_handling"
        
        # Security tests
        if any(x in name_lower for x in ['security', 'xss', 'injection', 'csrf', 'unauthorized']):
            return "security"
        
        # Edge case tests
        if any(x in name_lower for x in ['edge', 'boundary', 'empty', 'null', 'invalid', 'missing']):
            return "edge_case"
        
        # CRUD operations
        if any(x in name_lower for x in ['create', 'update', 'delete', 'get', 'list', 'fetch']):
            return "crud"
        
        # Happy path / functional
        if any(x in name_lower for x in ['valid', 'success', 'happy']):
            return "happy_path"
        
        return "functional"
    
    def generate(
        self,
        code_description: str,
        language: str = "python",
        max_tokens: int = 2048
    ) -> TestGenerationResult:
        """
        Generate test cases from a code description.
        
        Args:
            code_description: Description of the code/API to test
            language: Target language (python, javascript, etc.)
            max_tokens: Maximum tokens for generation
            
        Returns:
            TestGenerationResult with generated tests
        """
        import time
        start_time = time.time()
        
        try:
            # Build prompt
            prompt = self._build_prompt(code_description, language)
            
            # Generate response
            logger.info("Generating tests with local LLM...")
            response = self.llm.generate(
                prompt,
                max_tokens=max_tokens,
                temperature=0.1
            )
            
            # Log raw response for debugging
            logger.info(f"LLM raw response length: {len(response)} chars")
            logger.debug(f"LLM raw response: {response[:1000]}...")
            
            # Parse response
            test_data_list = self._parse_response(response)
            
            logger.info(f"Parsed {len(test_data_list)} test items from response")
            for i, item in enumerate(test_data_list[:3]):
                logger.debug(f"Parsed item {i}: type={type(item).__name__}, value={str(item)[:200]}")
            
            if not test_data_list:
                return TestGenerationResult(
                    success=False,
                    tests=[],
                    raw_response=response,
                    error="Failed to parse test cases from LLM response",
                    generation_time_ms=(time.time() - start_time) * 1000
                )
            
            # Normalize tests
            tests = []
            for i, test_data in enumerate(test_data_list):
                try:
                    test = self._normalize_test(test_data, i)
                    tests.append(test)
                except Exception as e:
                    logger.warning(f"Failed to normalize test {i}: {e}")
                    continue
            
            generation_time = (time.time() - start_time) * 1000
            logger.info(f"Generated {len(tests)} tests in {generation_time:.0f}ms")
            
            return TestGenerationResult(
                success=True,
                tests=tests,
                raw_response=response,
                generation_time_ms=generation_time
            )
            
        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return TestGenerationResult(
                success=False,
                tests=[],
                raw_response="",
                error=str(e),
                generation_time_ms=(time.time() - start_time) * 1000
            )


# Convenience function
def generate_tests(
    code_description: str,
    language: str = "python"
) -> Dict[str, Any]:
    """
    Generate test cases from a code description.
    
    Args:
        code_description: Description of the code/API to test
        language: Target language
        
    Returns:
        Dictionary with tests and metadata
        
    Example:
        >>> tests = generate_tests(
        ...     "POST /login accepts username and password. Returns 200 with token if valid.",
        ...     language="python"
        ... )
        >>> print(tests["tests"])
    """
    generator = TestGenerator()
    result = generator.generate(code_description, language)
    return result.to_dict()


# CLI for testing
if __name__ == "__main__":
    import sys
    
    # Example usage
    sample_description = """
    POST /login API endpoint:
    - Accepts JSON body with 'username' and 'password' fields
    - Returns 200 with JWT token if credentials are valid
    - Returns 401 if password is incorrect
    - Returns 400 if username or password is missing
    - Returns 429 if rate limit exceeded (more than 5 attempts per minute)
    """
    
    print("="*60)
    print("ETTA-X Test Generator")
    print("="*60)
    print(f"\nInput:\n{sample_description}")
    print("\nGenerating tests...")
    
    result = generate_tests(sample_description, "python")
    
    print(f"\nResult: {'Success' if result['success'] else 'Failed'}")
    print(f"Tests generated: {result['test_count']}")
    print(f"Time: {result['generation_time_ms']:.0f}ms")
    
    if result['tests']:
        print("\nGenerated Tests:")
        print(json.dumps(result['tests'], indent=2))
    
    if result.get('error'):
        print(f"\nError: {result['error']}")
