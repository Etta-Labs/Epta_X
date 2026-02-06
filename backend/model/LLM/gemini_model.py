"""
Gemini API Model for Test Generation
=====================================
Uses Google's Gemini API as a fallback when local LLM (Ollama) is not available.
This is used in hosted environments where GPU/local models aren't practical.

Usage:
    from backend.model.LLM.gemini_model import GeminiLLM, generate_tests_with_gemini
    
    llm = GeminiLLM()
    if llm.is_available():
        result = generate_tests_with_gemini(code_description="...")
"""

import os
import json
import logging
import re
import time
from typing import Optional, Dict, Any, List
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# Gemini API configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


class GeminiLLM:
    """
    Gemini API wrapper for test generation.
    Used as fallback when local Ollama is not available.
    """
    
    _instance: Optional['GeminiLLM'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.api_key = GEMINI_API_KEY
        self.model = GEMINI_MODEL
        self._initialized = True
    
    def is_available(self) -> bool:
        """Check if Gemini API is configured and available."""
        return bool(self.api_key)
    
    def get_status(self) -> Dict[str, Any]:
        """Get Gemini API status."""
        return {
            "loaded": self.is_available(),
            "using_gpu": False,
            "model_name": f"Gemini ({self.model})",
            "is_cloud": True,
            "error": None if self.is_available() else "GEMINI_API_KEY not set"
        }
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.1,
        **kwargs
    ) -> str:
        """
        Generate text using Gemini API.
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Returns:
            Generated text string
        """
        if not self.is_available():
            raise RuntimeError("Gemini API key not configured. Set GEMINI_API_KEY environment variable.")
        
        url = f"{GEMINI_API_URL}?key={self.api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "topP": 0.95,
                "topK": 40
            }
        }
        
        try:
            logger.info(f"Generating with Gemini ({self.model})...")
            
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=120
            )
            
            if response.status_code != 200:
                error = response.json().get("error", {}).get("message", response.text)
                raise RuntimeError(f"Gemini API error: {error}")
            
            result = response.json()
            
            # Extract text from response
            candidates = result.get("candidates", [])
            if not candidates:
                raise RuntimeError("No response from Gemini")
            
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            
            if not parts:
                raise RuntimeError("Empty response from Gemini")
            
            generated_text = parts[0].get("text", "")
            logger.info(f"Generated {len(generated_text)} chars with Gemini")
            
            return generated_text
            
        except requests.exceptions.Timeout:
            raise RuntimeError("Gemini API timeout")
        except requests.exceptions.ConnectionError:
            raise RuntimeError("Failed to connect to Gemini API")
        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            raise


# Test generation prompt template for Gemini
GEMINI_TEST_PROMPT = """You are an expert test engineer. Generate comprehensive test cases for the following code/API:

{code_description}

Generate test cases in JSON format. Each test should include:
- name: descriptive test name
- endpoint: API endpoint being tested
- method: HTTP method (GET, POST, PUT, DELETE)
- payload: request body/parameters as dict
- expected_status: expected HTTP status code
- description: what the test verifies
- category: one of (security, functional, edge_case, performance, validation)

Output ONLY valid JSON array of test objects. No markdown, no explanation.

Example format:
[
    {{
        "name": "test_login_valid_credentials",
        "endpoint": "/api/login",
        "method": "POST",
        "payload": {{"username": "test@example.com", "password": "secure123"}},
        "expected_status": 200,
        "description": "Verify login works with valid credentials",
        "category": "functional"
    }}
]

Generate 5-10 comprehensive tests covering happy path, edge cases, and security scenarios:"""


def generate_tests_with_gemini(
    code_description: str,
    language: str = "python"
) -> Dict[str, Any]:
    """
    Generate tests using Gemini API.
    
    Args:
        code_description: Description of code/API to test
        language: Target language for tests
        
    Returns:
        Dictionary with success status and generated tests
    """
    llm = GeminiLLM()
    
    if not llm.is_available():
        return {
            "success": False,
            "error": "Gemini API not configured",
            "tests": [],
            "model_used": "none"
        }
    
    start_time = time.time()
    
    try:
        prompt = GEMINI_TEST_PROMPT.format(code_description=code_description)
        
        response = llm.generate(prompt, max_tokens=4096, temperature=0.2)
        
        # Parse JSON from response
        tests = _parse_gemini_response(response)
        
        generation_time_ms = (time.time() - start_time) * 1000
        
        return {
            "success": True,
            "tests": tests,
            "test_count": len(tests),
            "raw_response": response,
            "generation_time_ms": generation_time_ms,
            "model_used": f"Gemini ({GEMINI_MODEL})",
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Gemini test generation failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "tests": [],
            "model_used": f"Gemini ({GEMINI_MODEL})"
        }


def _parse_gemini_response(response: str) -> List[Dict[str, Any]]:
    """Parse Gemini response to extract test cases."""
    
    # Clean up response
    cleaned = response.strip()
    
    # Remove markdown code blocks
    cleaned = re.sub(r'```json\s*', '', cleaned)
    cleaned = re.sub(r'```\s*', '', cleaned)
    
    # Try to find JSON array
    match = re.search(r'\[[\s\S]*\]', cleaned)
    if match:
        cleaned = match.group(0)
    
    try:
        tests = json.loads(cleaned)
        if isinstance(tests, list):
            # Validate and normalize each test
            valid_tests = []
            for test in tests:
                if isinstance(test, dict) and "name" in test:
                    valid_tests.append({
                        "name": test.get("name", "unnamed_test"),
                        "endpoint": test.get("endpoint", "/"),
                        "method": test.get("method", "GET").upper(),
                        "payload": test.get("payload", {}),
                        "expected_status": int(test.get("expected_status", 200)),
                        "description": test.get("description", ""),
                        "category": test.get("category", "functional"),
                        "priority_score": 0.5
                    })
            return valid_tests
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse Gemini response as JSON: {e}")
    
    return []


def get_gemini_instance() -> GeminiLLM:
    """Get singleton Gemini LLM instance."""
    return GeminiLLM()
