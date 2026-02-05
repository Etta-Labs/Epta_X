"""
Local LLM Model Loader (Ollama API)
===================================
Uses Ollama's local API for fast LLM inference.
Ollama must be running with codellama:7b-instruct model loaded.

Usage:
    from backend.model.LLM.local_model import get_llm_instance
    
    llm = get_llm_instance()
    response = llm.generate("Your prompt here")
"""

import json
import logging
import re
import requests
from typing import Optional, Dict, Any, List
from threading import Lock

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ollama API configuration
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "codellama:7b-instruct"


class LocalLLM:
    """
    Local LLM wrapper using Ollama API for inference.
    
    Features:
    - Fast inference via Ollama's optimized runtime
    - Singleton pattern for consistency
    - Thread-safe generation
    - Automatic connection checking
    """
    
    _instance: Optional['LocalLLM'] = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.base_url = OLLAMA_BASE_URL
        self.model = OLLAMA_MODEL
        self.is_loaded = False
        self._gen_lock = Lock()
        self._initialized = True
        
    def load(self, force_cpu: bool = False) -> bool:
        """
        Check if Ollama is running and model is available.
        
        Returns:
            bool: True if Ollama is accessible
        """
        if self.is_loaded:
            return True
        
        try:
            # Check Ollama is running
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if r.status_code != 200:
                logger.error(f"Ollama not responding: {r.status_code}")
                return False
            
            # Check if model is available
            models = r.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            
            if not any(self.model in name for name in model_names):
                logger.warning(f"Model {self.model} not found. Available: {model_names}")
                logger.info(f"Run: ollama pull {self.model}")
                return False
            
            self.is_loaded = True
            logger.info(f"Ollama connected, model: {self.model}")
            return True
            
        except requests.exceptions.ConnectionError:
            logger.error("Ollama not running. Start with: ollama serve")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            return False
    
    def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stop: Optional[List[str]] = None,
        **kwargs
    ) -> str:
        """
        Generate text using Ollama API.
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate (default: 1024)
            temperature: Sampling temperature (default: 0.1)
            stop: Stop sequences
            **kwargs: Additional parameters
            
        Returns:
            Generated text string
        """
        if not self.is_loaded:
            if not self.load():
                raise RuntimeError("Failed to connect to Ollama")
        
        max_tokens = max_tokens or 1024
        temperature = temperature or 0.1
        
        # Build request payload
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        
        if stop:
            payload["options"]["stop"] = stop
        
        with self._gen_lock:
            try:
                logger.info(f"Generating with Ollama ({self.model})...")
                
                r = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=300  # 5 minute timeout
                )
                
                if r.status_code != 200:
                    logger.error(f"Ollama error: {r.status_code} - {r.text}")
                    raise RuntimeError(f"Ollama API error: {r.status_code}")
                
                result = r.json()
                response = result.get("response", "").strip()
                
                # Log timing info
                total_duration = result.get("total_duration", 0) / 1e9  # nanoseconds to seconds
                eval_count = result.get("eval_count", 0)
                logger.info(f"Generated {len(response)} chars in {total_duration:.2f}s ({eval_count} tokens)")
                
                return response
                
            except requests.exceptions.Timeout:
                logger.error("Ollama request timed out")
                raise RuntimeError("Ollama request timed out")
            except Exception as e:
                logger.error(f"Generation failed: {e}")
                raise
    
    def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Generate and parse JSON output from the model.
        
        Args:
            prompt: Input prompt (should request JSON output)
            **kwargs: Generation parameters
            
        Returns:
            Parsed JSON as dictionary
        """
        response = self.generate(prompt, **kwargs)
        
        # Try to extract JSON from response
        try:
            # Direct parse
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON block in markdown
        try:
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
                return json.loads(json_str.strip())
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
                return json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError):
            pass
        
        # Try to find JSON object/array with regex
        try:
            json_match = re.search(r'[\[{].*[\]}]', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass
        
        logger.warning(f"Failed to parse JSON from response: {response[:200]}...")
        return {"raw_response": response, "error": "Failed to parse JSON"}
    
    def unload(self):
        """Reset the connection state."""
        self.is_loaded = False
        logger.info("Ollama connection reset")
    
    def get_info(self) -> Dict[str, Any]:
        """Get information about the current model."""
        return {
            "backend": "ollama",
            "base_url": self.base_url,
            "model": self.model,
            "is_loaded": self.is_loaded,
        }


# Singleton instance getter
_llm_instance: Optional[LocalLLM] = None

def get_llm_instance() -> LocalLLM:
    """Get the singleton LLM instance."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = LocalLLM()
    return _llm_instance


# Convenience functions
def generate(prompt: str, **kwargs) -> str:
    """Generate text using the LLM."""
    return get_llm_instance().generate(prompt, **kwargs)


def generate_json(prompt: str, **kwargs) -> Dict[str, Any]:
    """Generate and parse JSON from the LLM."""
    return get_llm_instance().generate_json(prompt, **kwargs)
