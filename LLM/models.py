"""
Pydantic models for API request/response schemas.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class WorkerStatus(str, Enum):
    """Worker status enumeration."""
    ONLINE = "online"
    OFFLINE = "offline"
    STARTING = "starting"
    ERROR = "error"


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    worker_status: WorkerStatus
    worker_url: Optional[str] = None


class WorkerRegisterRequest(BaseModel):
    """Request to register a worker URL."""
    worker_url: str = Field(..., description="The Cloudflare tunnel URL of the worker")
    model_name: Optional[str] = Field(None, description="Name of the loaded model")


class WorkerRegisterResponse(BaseModel):
    """Response after registering a worker."""
    success: bool
    message: str


class GenerateTestsRequest(BaseModel):
    """Request to generate tests using the LLM."""
    code: str = Field(..., description="The source code to generate tests for")
    language: str = Field("python", description="Programming language of the code")
    test_framework: Optional[str] = Field(None, description="Test framework to use (e.g., pytest, jest)")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens to generate")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Sampling temperature")
    additional_context: Optional[str] = Field(None, description="Additional context or instructions")


class GeneratedTest(BaseModel):
    """A single generated test case."""
    name: str
    description: str
    code: str
    test_type: str = Field(default="unit", description="Type of test: unit, integration, etc.")


class GenerateTestsResponse(BaseModel):
    """Response containing generated tests."""
    success: bool
    tests: Optional[List[GeneratedTest]] = None
    raw_response: Optional[str] = None
    error: Optional[str] = None
    tokens_used: Optional[int] = None


class CompletionRequest(BaseModel):
    """Generic completion request."""
    prompt: str = Field(..., description="The prompt to send to the LLM")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens to generate")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    stop: Optional[List[str]] = Field(None, description="Stop sequences")


class CompletionResponse(BaseModel):
    """Generic completion response."""
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
