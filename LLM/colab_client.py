"""
Colab Worker Client - Handles health checks and request forwarding to the Colab GPU worker.
"""
import httpx
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
import logging

from config import settings, get_worker_url, set_worker_url

logger = logging.getLogger(__name__)


class WorkerClient:
    """Client for communicating with the Colab GPU worker."""
    
    def __init__(self):
        self.last_activity: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None
    
    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=settings.worker_request_timeout)
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    def get_worker_url(self) -> Optional[str]:
        """Get the current worker URL."""
        return get_worker_url()
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check if the Colab worker is healthy and responsive.
        
        Returns:
            Dict with status, healthy boolean, and optional error message
        """
        worker_url = self.get_worker_url()
        
        if not worker_url:
            return {
                "healthy": False,
                "status": "no_worker_registered",
                "message": "No worker URL registered. Please start the Colab notebook."
            }
        
        try:
            client = await self.get_client()
            response = await client.get(
                f"{worker_url}{settings.worker_health_endpoint}",
                timeout=settings.worker_health_timeout
            )
            
            if response.status_code == 200:
                self.last_activity = datetime.utcnow()
                return {
                    "healthy": True,
                    "status": "online",
                    "worker_url": worker_url,
                    "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
                }
            else:
                return {
                    "healthy": False,
                    "status": "unhealthy",
                    "message": f"Worker returned status {response.status_code}"
                }
                
        except httpx.TimeoutException:
            return {
                "healthy": False,
                "status": "timeout",
                "message": "Worker health check timed out. Worker may be starting up."
            }
        except httpx.ConnectError:
            return {
                "healthy": False,
                "status": "unreachable",
                "message": "Cannot connect to worker. Colab runtime may have stopped."
            }
        except Exception as e:
            logger.exception("Health check failed")
            return {
                "healthy": False,
                "status": "error",
                "message": str(e)
            }
    
    async def wait_for_worker(self, max_attempts: Optional[int] = None) -> bool:
        """
        Poll until the worker becomes healthy.
        
        Args:
            max_attempts: Maximum number of poll attempts
            
        Returns:
            True if worker is healthy, False if max attempts reached
        """
        attempts = max_attempts or settings.worker_wake_max_attempts
        
        for i in range(attempts):
            logger.info(f"Waiting for worker... attempt {i + 1}/{attempts}")
            
            health = await self.health_check()
            if health["healthy"]:
                logger.info("Worker is now healthy!")
                return True
            
            await asyncio.sleep(settings.worker_wake_poll_interval)
        
        logger.warning(f"Worker did not become healthy after {attempts} attempts")
        return False
    
    async def generate_completion(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        stop: Optional[list] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send a completion request to the Colab worker.
        
        Args:
            prompt: The prompt to send to the LLM
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling parameter
            stop: Stop sequences
            **kwargs: Additional parameters to pass to llama-server
            
        Returns:
            Dict with the completion response or error
        """
        worker_url = self.get_worker_url()
        
        if not worker_url:
            return {
                "success": False,
                "error": "No worker registered. Please start the Colab notebook first."
            }
        
        # Build request payload for llama-server
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens or settings.default_max_tokens,
            "temperature": temperature or settings.default_temperature,
            "top_p": top_p or settings.default_top_p,
            "stream": False,
            **kwargs
        }
        
        if stop:
            payload["stop"] = stop
        
        try:
            client = await self.get_client()
            response = await client.post(
                f"{worker_url}{settings.worker_completion_endpoint}",
                json=payload,
                timeout=settings.worker_request_timeout
            )
            
            self.last_activity = datetime.utcnow()
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "data": response.json()
                }
            else:
                return {
                    "success": False,
                    "error": f"Worker returned status {response.status_code}",
                    "details": response.text
                }
                
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Request timed out. The model may be processing a large request."
            }
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Cannot connect to worker. Colab runtime may have stopped."
            }
        except Exception as e:
            logger.exception("Completion request failed")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_inactivity_seconds(self) -> Optional[int]:
        """Get seconds since last activity, or None if no activity recorded."""
        if self.last_activity is None:
            return None
        return int((datetime.utcnow() - self.last_activity).total_seconds())


# Global worker client instance
worker_client = WorkerClient()
