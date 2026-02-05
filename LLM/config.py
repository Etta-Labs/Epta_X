"""
Configuration management for the LLM Gateway.
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # FastAPI Settings
    app_name: str = "LLM Gateway"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    
    # Worker Settings
    worker_url: Optional[str] = None  # Set dynamically when Colab registers
    worker_health_endpoint: str = "/health"
    worker_completion_endpoint: str = "/completion"
    
    # Timeouts (seconds)
    worker_health_timeout: int = 5
    worker_request_timeout: int = 120  # LLM inference can be slow
    worker_wake_poll_interval: int = 10
    worker_wake_max_attempts: int = 30  # 5 minutes max wait
    
    # Inactivity Shutdown
    inactivity_timeout_minutes: int = 15
    
    # Worker Registry (file-based for simplicity)
    worker_registry_file: str = "/tmp/llm_worker_url.txt"
    
    # API Key for securing endpoints (optional)
    api_key: Optional[str] = None
    
    # LLM Default Parameters
    default_max_tokens: int = 2048
    default_temperature: float = 0.7
    default_top_p: float = 0.9
    
    class Config:
        env_file = ".env"
        env_prefix = "LLM_"


settings = Settings()


def get_worker_url() -> Optional[str]:
    """Get the current worker URL from registry file."""
    if os.path.exists(settings.worker_registry_file):
        with open(settings.worker_registry_file, "r") as f:
            url = f.read().strip()
            return url if url else None
    return None


def set_worker_url(url: str) -> None:
    """Set the worker URL in registry file."""
    with open(settings.worker_registry_file, "w") as f:
        f.write(url)


def clear_worker_url() -> None:
    """Clear the worker URL from registry."""
    if os.path.exists(settings.worker_registry_file):
        os.remove(settings.worker_registry_file)
